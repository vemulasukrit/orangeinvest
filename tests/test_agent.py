import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from errand.agent import Agent
from errand.tools import TZ


class SimulatedCrash(BaseException):
    pass


class AgentTests(unittest.TestCase):
    def setUp(self):
        fixed=datetime(2026,10,31,9,0,tzinfo=TZ)
        for target in ('errand.tools.now','errand.agent.now'):
            patcher=patch(target,return_value=fixed)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'test.db')
        self.a = Agent(self.path)
        self.sid = self.a.snapshot()['session_id']

    def tearDown(self):
        self.final_snapshot = self.a.snapshot(self.sid)
        self.a.close()
        self.tmp.cleanup()

    def act(self, event, **payload):
        self.last_snapshot = self.a.act(self.sid, event, payload)
        return self.last_snapshot

    def ticket(self, scenario='success'):
        self.act('scenario', name=scenario)
        s = self.act('facts', changes=dict(service='plumbing', area='Indiranagar', date_range='tomorrow', time_window='morning', budget=2000))
        p = s['providers'][0]
        return self.act('select', provider_id=p['id'], slot=p['free_slots'][0])

    def approve(self, s):
        p = s['proposal']
        return self.act('approve', proposal_id=p['id'], fingerprint=p['fingerprint'])

    def test_collects_missing(self):
        s = self.act('chat', text='Need a plumber')
        self.assertEqual(s['facts']['service'], 'plumbing')
        self.assertFalse(s['bookings'])

    def test_success_requires_approval(self):
        s = self.ticket()
        self.assertFalse(s['bookings'])
        self.assertEqual(self.approve(s)['state'], 'completed')

    def test_repeat_is_idempotent(self):
        s = self.ticket()
        self.approve(s)
        self.assertEqual(len(self.approve(s)['bookings']), 1)

    def test_stale_fingerprint(self):
        s = self.ticket()
        self.assertTrue(self.act('approve', proposal_id=s['proposal']['id'], fingerprint='bad')['error'])

    def test_edit_invalidates(self):
        s = self.ticket()
        self.act('facts', changes={'budget': 3000})
        self.assertTrue(self.approve(s)['error'])

    def test_timeout_after_success(self):
        s = self.approve(self.ticket('timeout_after_success'))
        self.assertEqual(len(s['bookings']), 1)
        self.assertTrue(any(t['name'] == 'get_booking_status' for t in s['traces']))

    def test_timeout_not_booked(self):
        s = self.approve(self.ticket('timeout_not_booked'))
        self.assertFalse(s['bookings'])

    def test_slot_taken(self):
        self.assertFalse(self.approve(self.ticket('slot_taken'))['bookings'])

    def test_price_change(self):
        s = self.ticket('price_change')
        self.assertEqual(s['proposal']['price'], s['providers'][0]['price']+100)
        self.assertEqual(self.approve(s)['state'], 'completed')

    def test_slot_unavailable(self):
        self.assertTrue(self.ticket('slot_unavailable')['error'])

    def test_unknown_error_blocks(self):
        self.assertEqual(self.approve(self.ticket('unknown_error'))['state'], 'blocked')

    def test_limit(self):
        self.assertTrue(self.approve(self.ticket('limit_exhaustion'))['error'])

    def test_cancel_retries(self):
        b = self.approve(self.ticket())['bookings'][0]
        s = self.act('cancel', booking_id=b['id'])
        self.assertEqual(s['bookings'][0]['status'], 'booked')
        s = self.approve(s)
        self.assertEqual(s['bookings'][0]['status'], 'cancelled')

    def test_reschedule_conflict(self):
        from datetime import datetime, timedelta
        b = self.approve(self.ticket())['bookings'][0]
        self.act('scenario', name='reschedule_conflict')
        new_slot=(datetime.fromisoformat(b['slot'])+timedelta(days=1)).isoformat()
        s = self.act('reschedule', booking_id=b['id'], slot=new_slot)
        s=self.approve(s)
        self.assertIn('slot_conflict',s['error'])
        self.assertEqual(s['bookings'][0]['slot'], b['slot'])

    def test_memory_forget(self):
        self.act('memory', op='set', key='area', value='Whitefield')
        s = self.act('new')
        self.sid = s['session_id']
        self.assertEqual(s['facts']['area'], 'Whitefield')
        s = self.act('memory', op='forget', key='area')
        self.assertNotIn('area', s['facts'])

    def test_inferred_needs_confirmation(self):
        s = self.act('chat', text='I usually prefer mornings')
        self.assertFalse(s['memory'][0]['confirmed'])
        s = self.act('new')
        self.assertNotIn('earliest_time', s['facts'])

    def test_restart_pending(self):
        s = self.ticket('timeout_after_success')
        original=self.a.tools.book
        def crash(*args):
            original(*args)
            raise SimulatedCrash()
        self.a.tools.book=crash
        with self.assertRaises(SimulatedCrash):
            self.approve(s)
        self.a.close()
        self.a = Agent(self.path)
        s = self.act('recover')
        self.assertEqual(len(s['bookings']), 1)

    def test_injection_ignored(self):
        s = self.ticket()
        self.assertFalse(s['bookings'])
        self.assertTrue(any('ignore' in r.lower() for p in s['providers'] for r in p['reviews']))

    def test_invalid_event_message(self):
        s = self.act('unsupported')
        self.assertTrue(s['error'])
        self.assertEqual(s['messages'][-1]['role'], 'assistant')

    def test_next_week_slots_match_request(self):
        from datetime import timedelta
        from errand.tools import now
        self.ticket()
        s = self.act('facts', changes={'date_range': 'next week'})
        self.assertEqual(s['providers'][0]['free_slots'][0][:10], (now()+timedelta(days=7)).date().isoformat())

    def test_memory_set_validates_time(self):
        s = self.act('memory', op='set', key='earliest_time', value='99:99')
        self.assertTrue(s['error'])

    def test_forget_preserves_pending_recovery(self):
        self.act('memory', op='set', key='area', value='Whitefield')
        self.sid = self.act('new')['session_id']
        self.ticket()
        original=self.a.tools.book
        def crash(*args):
            original(*args)
            raise SimulatedCrash()
        self.a.tools.book=crash
        with self.assertRaises(SimulatedCrash):
            self.approve(self.a.snapshot(self.sid))
        self.act('memory', op='forget', key='area')
        self.assertEqual(self.act('recover')['state'], 'completed')

    def test_empty_area_rejected(self):
        s = self.act('facts', changes={'area': '   '})
        self.assertTrue(s['error'])

    def test_fixed_provider_contract(self):
        t = self.a.tools
        providers = t.search_providers('plumbing', 'Indiranagar', 'tomorrow')
        self.assertGreaterEqual(len(providers), 3)
        p = t.get_provider(providers[0]['id'])
        self.assertTrue(p['reviews'])
        h = t.hold_slot(p['id'], p['free_slots'][0])
        self.assertIn('quoted_price', h)
        t.scenario = 'success'
        b = t.book(h['hold_id'], 'contract-key')
        self.assertIn('booking_id', b)
        self.assertEqual(t.get_booking_status('contract-key')['status'], 'booked')
        self.assertEqual(t.book(h['hold_id'], 'contract-key')['booking_id'], b['booking_id'])
        self.assertTrue(t.list_bookings(t.user_id))

    def test_unknown_exception_has_message(self):
        self.a.tools.search_providers = lambda *args: (_ for _ in ()).throw(RuntimeError('private provider details'))
        s = self.act('facts', changes=dict(service='plumbing', area='Indiranagar', date_range='tomorrow', time_window='morning', budget=2000))
        self.assertTrue(s['error'])
        self.assertNotIn('private provider details', s['messages'][-1]['text'])

    def test_cancel_retry_exhaustion(self):
        b = self.approve(self.ticket())['bookings'][0]
        s = self.act('cancel', booking_id=b['id'])
        self.a.tools.cancel = lambda *args: {'status':'error', 'code':503}
        s = self.approve(s)
        self.assertTrue(s['error'])
        self.assertEqual(s['bookings'][0]['status'], 'booked')

    def test_tool_call_cap(self):
        s = self.ticket()
        self.a.calls = 8
        with self.assertRaises(ValueError):
            self.a._tool(s, 'capped', lambda: None)

    def test_wall_time_cap(self):
        import time
        s = self.ticket()
        self.a.started = time.monotonic()-4
        with self.assertRaises(ValueError):
            self.a._tool(s, 'capped', lambda: None)

    def test_hold_expiry(self):
        from datetime import timedelta
        from errand.tools import now
        from unittest.mock import patch
        s = self.ticket()
        with patch('errand.agent.now',return_value=now()+timedelta(minutes=11)):
            s=self.approve(s)
        self.assertIn('expired',s['error'])

    def test_cross_session_approval_rejected(self):
        s = self.ticket()
        old = self.sid
        self.sid = self.act('new')['session_id']
        self.assertTrue(self.approve(s)['error'])
        self.assertFalse(self.a.snapshot(old)['bookings'])

    def test_time_change_invalidates(self):
        s = self.ticket()
        self.act('facts', changes={'time_window':'evening'})
        self.assertTrue(self.approve(s)['error'])

    def test_single_interpreter_turn(self):
        s = self.act('chat', text='Need a plumber in Indiranagar tomorrow morning under 2000')
        self.assertEqual(sum(t['result'].get('interpreter_turns',0) for t in s['traces'] if t['kind']=='model'),1)

    def test_mutated_hold_rejected(self):
        import json
        s = self.ticket()
        hid = s['proposal']['hold_id']
        row = self.a.store.db.execute('SELECT body FROM holds WHERE id=?',(hid,)).fetchone()
        h = json.loads(row[0]); h['quoted_price'] += 100
        with self.a.store.db:
            self.a.store.db.execute('UPDATE holds SET body=? WHERE id=?',(json.dumps(h),hid))
        self.assertTrue(self.approve(s)['error'])
        self.assertFalse(self.a.snapshot(self.sid)['bookings'])

    def test_bookings_visible_in_new_errand(self):
        self.approve(self.ticket())
        self.assertEqual(len(self.act('new')['bookings']),1)

    def test_receipt_booking_id(self):
        s = self.approve(self.ticket())
        self.assertEqual(s['proposal']['booking_id'],s['bookings'][0]['id'])

    def test_engine_model_limit(self):
        self.a.model_limit = 0
        self.assertTrue(self.act('chat',text='Need a plumber')['error'])

    def test_engine_wall_limit(self):
        self.a.wall_limit = 0
        s = self.act('facts',changes=dict(service='plumbing',area='Indiranagar',date_range='tomorrow',time_window='morning',budget=2000))
        self.assertTrue(s['error'])

    def test_starter_conversations(self):
        for text, service, budget in [('Find a plumber in Indiranagar this week, mornings only, under ₹1,500.','plumbing',1500),('Find AC servicing in Indiranagar next week, mornings, under ₹2,000.','ac',2000),('Find an electrician in Indiranagar this week, after 10 am, under ₹1,500.','electrical',1500)]:
            self.sid = self.act('new')['session_id']
            s = self.act('chat',text=text)
            self.assertEqual(s['facts']['budget'],budget)
            self.assertEqual(s['facts']['service'],service)
            self.assertEqual(s['state'],'choosing')

    def test_missing_fact_conversation(self):
        for text in ['Need a plumber','Indiranagar','tomorrow morning','1500']:
            s=self.act('chat',text=text)
        self.assertEqual(s['state'],'choosing')
        self.assertEqual(s['facts']['budget'],1500)

    def test_chat_cancel_prepares_approval(self):
        self.approve(self.ticket())
        s=self.act('chat',text='Cancel my booking')
        self.assertEqual(s['proposal']['action'],'cancel')
        self.assertEqual(s['bookings'][0]['status'],'booked')

    def test_chat_reschedule_prepares_approval(self):
        self.approve(self.ticket())
        s=self.act('chat',text='Move my plumbing booking to Saturday')
        self.assertEqual(s['proposal']['action'],'reschedule')

    def test_quote_over_budget_rejected(self):
        s=self.ticket()
        self.act('facts',changes={'budget':600})
        self.act('scenario',name='price_change')
        p=self.a.snapshot(self.sid)['providers'][0]
        s=self.act('select',provider_id=p['id'],slot=p['free_slots'][0])
        self.assertTrue(s['error'])
        self.assertIsNone(s['proposal'])

    def test_preferred_technician_constraint(self):
        self.ticket()
        s=self.act('facts',changes={'preferred_technician':'City Service Co.'})
        self.assertEqual([p['name'] for p in s['providers']],['City Service Co.'])

    def test_other_prepared_approval_blocked_while_pending(self):
        first=self.ticket('success')
        first_sid=self.sid
        self.sid=self.act('new')['session_id']
        second=self.ticket('unknown_error')
        self.approve(second)
        self.sid=first_sid
        s=self.approve(first)
        self.assertTrue(s['error'])
        self.assertFalse(s['bookings'])

    def test_completed_operation_reconstructs_receipt(self):
        s=self.approve(self.ticket())
        stale=self.a.store.get(self.sid)
        stale['state']='executing'; stale['proposal']['status']='approved'
        stale['proposal'].pop('booking_id',None)
        self.a.store.save(stale)
        s=self.act('recover')
        self.assertEqual(s['state'],'completed')
        self.assertEqual(s['proposal']['booking_id'],s['bookings'][0]['id'])

    def test_unsupported_date_does_not_silently_book_tomorrow(self):
        s=self.act('facts',changes=dict(service='plumbing',area='Indiranagar',date_range='someday',time_window='morning',budget=2000))
        self.assertTrue(s['error'])
        self.assertFalse(s['providers'])

    def test_trace_runs_persist_beyond_snapshot(self):
        self.act('chat',text='Need a plumber')
        run=self.a.store.db.execute('SELECT run_id FROM traces LIMIT 1').fetchone()[0]
        self.a.close(); self.a=Agent(self.path)
        self.assertTrue(self.a.store.db.execute('SELECT body FROM traces WHERE run_id=?',(run,)).fetchall())

    def test_slow_read_hard_deadline(self):
        import time
        original=self.a.tools.search_providers
        def slow(*args):
            time.sleep(.8)
            return original(*args)
        self.a.tools.search_providers=slow
        self.a.wall_limit=.3
        start=time.monotonic()
        s=self.act('facts',changes=dict(service='plumbing',area='Indiranagar',date_range='tomorrow',time_window='morning',budget=2000))
        elapsed=time.monotonic()-start
        time.sleep(.9)
        self.assertLess(elapsed,.7)
        self.assertTrue(s['error'])

    def test_slow_mutation_reconciles_before_replacement(self):
        import time
        ticket=self.ticket()
        original=self.a.tools.book
        def slow(*args):
            time.sleep(.8)
            return original(*args)
        self.a.tools.book=slow
        self.a.wall_limit=.3
        start=time.monotonic()
        s=self.approve(ticket)
        elapsed=time.monotonic()-start
        blocked=self.act('new')
        time.sleep(.9)
        self.a.wall_limit=3
        s=self.act('recover')
        self.assertLess(elapsed,.7)
        self.assertTrue(blocked['error'])
        self.assertEqual(s['state'],'completed')
        self.assertEqual(len(s['bookings']),1)

    def test_optional_fact_clear(self):
        self.ticket()
        self.act('facts',changes={'earliest_time':'11:00','preferred_technician':'City Service Co.'})
        s=self.act('facts',changes={'earliest_time':None,'preferred_technician':None})
        self.assertNotIn('earliest_time',s['facts'])
        self.assertNotIn('preferred_technician',s['facts'])

    def test_not_before_dotted_time(self):
        s=self.act('chat',text='Find an electrician in Indiranagar tomorrow, not before 10 a.m., under ₹1,500')
        self.assertEqual(s['facts']['earliest_time'],'10:00')

    def test_any_time_clears_earliest(self):
        self.ticket()
        self.act('facts',changes={'earliest_time':'11:00'})
        s=self.act('chat',text='any time')
        self.assertNotIn('earliest_time',s['facts'])

    def test_distinct_holds_cannot_double_book_provider_slot(self):
        t=self.a.tools
        t.scenario='success'
        p=t.search_providers('plumbing','Indiranagar','tomorrow')[0]
        slot=p['free_slots'][0]
        one=t.hold_slot(p['id'],slot); two=t.hold_slot(p['id'],slot)
        self.assertEqual(t.book(one['hold_id'],'one')['status'],'booked')
        self.assertEqual(t.book(two['hold_id'],'two')['status'],'slot_taken')
        self.assertEqual(t.hold_slot(p['id'],slot)['status'],'slot_unavailable')
        found=t.search_providers('plumbing','Indiranagar','tomorrow')[0]
        self.assertNotIn(slot,found['free_slots'])

    def test_reschedule_actual_occupied_slot_preserves_original(self):
        t=self.a.tools
        t.scenario='success'
        p=t.search_providers('plumbing','Indiranagar','tomorrow')[0]
        first,second=p['free_slots'][:2]
        a=t.book(t.hold_slot(p['id'],first)['hold_id'],'a')
        t.book(t.hold_slot(p['id'],second)['hold_id'],'b')
        result=t.reschedule(a['booking_id'],second,'move-a')
        self.assertEqual(result['status'],'slot_conflict')
        booking=next(b for b in t.list_bookings(t.user_id) if b['id']==a['booking_id'])
        self.assertEqual(booking['slot'],first)

    def test_equivalent_slot_encodings_cannot_bypass_occupancy(self):
        from datetime import datetime, timezone
        t=self.a.tools
        t.scenario='success'
        p=t.search_providers('plumbing','Indiranagar','tomorrow')[0]
        first,second=p['free_slots'][:2]
        t.book(t.hold_slot(p['id'],first)['hold_id'],'first')
        b=t.book(t.hold_slot(p['id'],second)['hold_id'],'second')
        utc=datetime.fromisoformat(first).astimezone(timezone.utc)
        variants=[utc.isoformat(),utc.isoformat(timespec='microseconds'),first.replace('+05:30','.000000+05:30')]
        for i,variant in enumerate(variants):
            with self.subTest(slot=variant):
                result=t.reschedule(b['booking_id'],variant,f'equivalent-{i}')
                self.assertEqual(result['status'],'slot_conflict')
        booking=next(bk for bk in t.list_bookings(t.user_id) if bk['id']==b['booking_id'])
        self.assertEqual(booking['slot'],second)

    def test_reschedule_proposal_canonicalizes_offset(self):
        from datetime import datetime, timezone, timedelta
        b=self.approve(self.ticket())['bookings'][0]
        instant=datetime.fromisoformat(b['slot'])+timedelta(days=1)
        s=self.act('reschedule',booking_id=b['id'],slot=instant.astimezone(timezone.utc).isoformat(timespec='microseconds'))
        self.assertEqual(s['proposal']['slot'],instant.isoformat())

    def test_http_transport_guards(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import json
        from server import handler
        server = ThreadingHTTPServer(('127.0.0.1',0), handler(self.a))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(url+'/api/state') as response:
                self.assertIn('session_id', json.load(response))
            request = Request(url+'/api/action',data=b'{}',headers={'Origin':'https://evil.example','Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code,403)
            with self.assertRaises(HTTPError) as caught:
                urlopen(url+'/%2e%2e/server.py')
            self.assertEqual(caught.exception.code,404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
