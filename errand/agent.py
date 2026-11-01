"""Approval-first state machine with durable operation recovery."""
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime
from .store import Store
from .tools import Tools, now, canonical_slot
from .interpreter import interpret

SCENARIOS = {'seeded', 'success', 'timeout_after_success', 'timeout_not_booked', 'slot_taken', 'price_change', 'slot_unavailable', 'reschedule_conflict', 'unknown_error', 'limit_exhaustion'}
REQUIRED = ('service', 'area', 'date_range', 'time_window', 'budget')


class Agent:
    def __init__(self, db_path):
        self.store = Store(db_path)
        self.tools = Tools(self.store)
        self.lock = threading.RLock()
        self.model_limit, self.tool_limit, self.wall_limit = 1, 8, 3
        self.inflight = None

    def close(self):
        self.store.db.close()

    def _new(self):
        s = dict(session_id=uuid.uuid4().hex, state='collecting', facts={}, messages=[], providers=[], proposal=None, bookings=[], memory=[], traces=[], scenario='seeded', error=None)
        for m in self.store.memories():
            if m['confirmed']:
                s['facts'][m['key']] = m['value']
        s['inherited'] = list(s['facts'])
        self._say(s, 'What can I take off your list?')
        self.store.save(s)
        return s

    def snapshot(self, session_id=None):
        with self.lock:
            s = self.store.get(session_id)
            if not s:
                s = self._new()
            s['bookings'] = self.store.bookings('local-user')
            s['memory'] = self.store.memories()
            return {k: v for k, v in s.items() if k != 'inherited'}

    def _say(self, s, text):
        s['messages'].append({'role': 'assistant', 'text': text})

    def _trace(self, s, kind, name, args=None, result=None, latency=0):
        def clean(value):
            if isinstance(value, dict):
                return {k: ('[redacted]' if v is not None and any(w in k.lower() for w in ('password','secret','token','authorization')) else clean(v)) for k,v in value.items()}
            if isinstance(value, (list,tuple)):
                return [clean(v) for v in value]
            if isinstance(value, str):
                return re.sub(r'(?i)(?:sk-[\w-]+|bearer\s+\S+|(?:password|secret|api[_ -]?key)\s*[:=]\s*\S+)', '[redacted]',value)
            return value
        args, result = clean(args), clean(result)
        entry = dict(id=uuid.uuid4().hex, at=now().isoformat(), kind=kind, name=name, args=args or {}, result=result or {}, latency_ms=round(latency, 3), run_id=self.run_id)
        s['traces'].append(entry)
        with self.store.db:
            self.store.db.execute('INSERT INTO traces VALUES (?,?,?,?)',(entry['id'],self.run_id,s['session_id'],json.dumps(entry)))
        s['traces'] = s['traces'][-250:]

    def _state(self, s, state):
        old = s['state']
        s['state'] = state
        self._trace(s, 'transition', f'{old} → {state}')

    def _tool(self, s, name, fn, *args):
        self.calls += 1
        if self.calls > self.tool_limit or time.monotonic() - self.started >= self.wall_limit:
            raise ValueError('This turn reached its execution limit. No further action was taken.')
        start = time.monotonic()
        completed=threading.Event()
        box={}
        def invoke():
            try:
                box['result']=fn(*args)
            except BaseException as exc:
                box['exception']=exc
            finally:
                self.store.close_thread()
                completed.set()
        self.inflight=completed
        threading.Thread(target=invoke,daemon=True,name='errand-tool').start()
        if not completed.wait(max(0,self.wall_limit-(time.monotonic()-self.started))):
            self._trace(s, 'tool', name, {'arguments':args}, {'status':'wall_limit'}, (time.monotonic()-start)*1000)
            raise ValueError('This turn reached its wall-clock limit. Recover any pending operation.')
        self.inflight=None
        if 'exception' in box:
            self._trace(s, 'tool', name, {'arguments': args}, {'status':'exception'}, (time.monotonic()-start)*1000)
            raise box['exception']
        result=box['result']
        self._trace(s, 'tool', name, {'arguments': args}, result, (time.monotonic()-start)*1000)
        return result

    def _memory(self, key, value, source='stated', confirmed=True):
        if key not in ('area', 'earliest_time', 'preferred_technician'):
            raise ValueError('Only area, earliest_time and preferred_technician are reusable preferences.')
        if not isinstance(value, str) or not value.strip() or len(value)>150:
            raise ValueError('Preference must be short nonempty text.')
        if key == 'earliest_time' and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('Earliest time must be HH:MM.')
        m = dict(key=key, value=value, source=source, confirmed=confirmed)
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO memory VALUES (?,?)', (key, json.dumps(m)))

    def _facts(self, s, changes):
        if not isinstance(changes, dict) or any(k not in REQUIRED+('earliest_time', 'preferred_technician') for k in changes):
            raise ValueError('Please provide supported ticket facts.')
        merged = {**s['facts'], **changes}
        for key in ('earliest_time','preferred_technician'):
            if merged.get(key,'present') is None:
                merged.pop(key,None)
        if any(isinstance(v, str) and not v.strip() for v in merged.values()):
            raise ValueError('Facts cannot contain blank text.')
        if 'service' in merged and merged['service'] not in ('plumbing', 'electrical', 'ac', 'cleaning'):
            raise ValueError('Choose plumbing, electrical, ac or cleaning.')
        if 'budget' in merged and (type(merged['budget']) is not int or not 1 <= merged['budget'] <= 1000000):
            raise ValueError('Budget must be a positive integer amount in INR.')
        if 'time_window' in merged and merged['time_window'] not in ('morning', 'afternoon', 'evening', 'any'):
            raise ValueError('Choose morning, afternoon, evening or any.')
        if 'earliest_time' in merged and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(merged['earliest_time'])):
            raise ValueError('Earliest time must be HH:MM.')
        if any(not isinstance(v, (str, int)) or len(str(v)) > 150 for v in merged.values()):
            raise ValueError('Facts must be short text or a budget amount.')
        s['facts'] = merged
        s['proposal'] = None
        for k in changes:
            if k in s.get('inherited', []):
                s['inherited'].remove(k)
        if all(merged.get(k) for k in REQUIRED):
            providers = self._tool(s, 'search_providers', self.tools.search_providers, merged['service'], merged['area'], merged['date_range'])
            window = merged['time_window']
            earliest = merged.get('earliest_time', '00:00')
            for p in providers:
                p['free_slots'] = [slot for slot in p['free_slots'] if slot[11:16]>=earliest and (window=='any' or (window=='morning' and int(slot[11:13])<12) or (window=='afternoon' and 12<=int(slot[11:13])<17) or (window=='evening' and int(slot[11:13])>=17))]
            s['providers'] = [p for p in providers if p['price']<=merged['budget'] and p['free_slots']]
            if merged.get('preferred_technician'):
                preferred=merged['preferred_technician'].lower()
                s['providers']=[p for p in s['providers'] if preferred in (p['id'].lower(),p['name'].lower())]
            self._state(s, 'choosing')
            self._say(s, 'Compare providers and choose an exact slot.' if s['providers'] else 'No providers fit this budget. Please increase it or change your request.')
        else:
            self._state(s, 'collecting')
            self._say(s, 'I still need: '+', '.join(k for k in REQUIRED if not merged.get(k))+'.')

    def _proposal(self, s, p):
        p.update(id=uuid.uuid4().hex, revision=len([t for t in s['traces'] if t['kind']=='approval'])+1, status='awaiting_approval')
        p['fingerprint'] = hashlib.sha256(json.dumps({'session': s['session_id'], **p}, sort_keys=True).encode()).hexdigest()
        s['proposal'] = p
        self._state(s, 'awaiting_approval')
        self._say(s, f"Review {p['action']}: {p['provider_name']}, {p['slot']}, INR {p['price']}. Approve this exact ticket to continue.")

    def _finish(self, s, op, result):
        if result['status'] in ('booked', 'cancelled'):
            s['proposal']['booking_id'] = result['booking_id']
            s['proposal']['status'] = 'completed'
            self._state(s, 'completed')
            self._say(s, 'Verified receipt: '+s['proposal']['action']+' completed successfully.')
        elif result['status'] in ('unknown', 'not_found'):
            self._state(s, 'blocked')
            self._say(s, 'The provider outcome is unresolved. A replacement is blocked; use Recover to check status.')
            s['error'] = 'Unresolved provider outcome'
            self.store.save(s)
            return
        else:
            self._state(s, 'choosing')
            s['error'] = 'Provider did not complete the action: '+result['status']
            self._say(s, s['error']+'. Review a fresh ticket to try again.')
            s['proposal'] = None
        with self.store.db:
            self.store.db.execute('UPDATE operations SET result=? WHERE id=?', (json.dumps(result), op))
            self.store.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)',(s['session_id'],json.dumps(s)))

    def _approve(self, s, payload):
        p = s['proposal']
        if not p or p['id'] != payload.get('proposal_id') or p['fingerprint'] != payload.get('fingerprint'):
            raise ValueError('That approval is stale. Review the current exact ticket.')
        prior = self.store.db.execute('SELECT result FROM operations WHERE id=?', (p['id'],)).fetchone()
        if prior:
            if prior[0]:
                self._finish(s,p['id'],json.loads(prior[0]))
                self._say(s, 'This approval was already processed; its recorded result is unchanged.')
                return
            return self._recover(s)
        material = {k:v for k,v in p.items() if k!='fingerprint'}
        material['status'] = 'awaiting_approval'
        expected = hashlib.sha256(json.dumps({'session':s['session_id'], **material},sort_keys=True).encode()).hexdigest()
        if expected != p['fingerprint']:
            raise ValueError('Ticket material changed. Select and approve a fresh ticket.')
        if datetime.fromisoformat(p['expires_at']) <= now():
            s['proposal'] = None
            raise ValueError('The ten-minute hold expired. Select a fresh slot and approve again.')
        if s['scenario'] == 'slot_unavailable':
            s['proposal'] = None
            self._state(s, 'choosing')
            raise ValueError('The price or slot changed. Your approval was invalidated; select again for a fresh quote.')
        if p['action']=='book':
            row = self.store.db.execute('SELECT body FROM holds WHERE id=?',(p['hold_id'],)).fetchone()
            h = json.loads(row[0]) if row else {}
            if not h or h['quoted_price']!=p['price'] or h['slot']!=p['slot'] or h['provider']['id']!=p['provider_id'] or datetime.fromisoformat(h['expires_at'])<=now():
                s['proposal']=None
                raise ValueError('The held price or slot changed. Review a fresh ticket before approval.')
        with self.store.db:
            self.store.db.execute('INSERT INTO approvals VALUES (?,?,?,?)', (p['id'], s['session_id'], p['fingerprint'], json.dumps(p)))
            self.store.db.execute('INSERT INTO operations VALUES (?,?,?,NULL)', (p['id'], s['session_id'], json.dumps(p)))
        p['status'] = 'approved'
        self._trace(s, 'approval', 'explicit_owner_bound_approval', {'proposal_id': p['id'], 'fingerprint': p['fingerprint']})
        self._state(s, 'executing')
        self.store.save(s)
        self.tools.user_id = 'local-user'
        self.tools.scenario = s['scenario']
        name = p['action']
        args = (p['hold_id'], p['id']) if name=='book' else (p['booking_id'], p['id']) if name=='cancel' else (p['booking_id'], p['slot'], p['id'])
        result = self._tool(s, name, getattr(self.tools, name), *args)
        if result.get('code') == 503:
            result = self._tool(s, 'cancel', self.tools.cancel, *args)
        if result['status'] == 'timeout':
            self._state(s, 'reconciling')
            result = self._tool(s, 'get_booking_status', self.tools.get_booking_status, p['id'])
        self._finish(s, p['id'], result)

    def _recover(self, s):
        row = self.store.db.execute('SELECT id,body FROM operations WHERE session_id=? AND result IS NULL ORDER BY rowid LIMIT 1', (s['session_id'],)).fetchone()
        if not row:
            if s['state'] in ('executing','reconciling'):
                done=self.store.db.execute('SELECT id,body,result FROM operations WHERE session_id=? AND result IS NOT NULL ORDER BY rowid DESC LIMIT 1',(s['session_id'],)).fetchone()
                if done:
                    s['proposal']=json.loads(done[1])
                    self._finish(s,done[0],json.loads(done[2]))
                    return
            self._say(s, 'There is no pending operation to recover.')
            return
        s['proposal'] = json.loads(row[1])
        self._state(s, 'reconciling')
        result = self._tool(s, 'get_booking_status', self.tools.get_booking_status, row[0])
        if result['status'] == 'not_found':
            p = s['proposal']
            self.tools.user_id, self.tools.scenario = 'local-user', s['scenario']
            name = p['action']
            args = (p['hold_id'], p['id']) if name=='book' else (p['booking_id'], p['id']) if name=='cancel' else (p['booking_id'], p['slot'], p['id'])
            result = self._tool(s, name, getattr(self.tools, name), *args)
            if result.get('code')==503:
                result = self._tool(s, name, getattr(self.tools, name), *args)
            if result['status']=='timeout':
                result = self._tool(s, 'get_booking_status', self.tools.get_booking_status, row[0])
        self._finish(s, row[0], result)

    def act(self, session_id, event, payload):
        with self.lock:
            self.run_id = uuid.uuid4().hex
            self.calls, self.started = 0, time.monotonic()
            s = self.store.get(session_id)
            if not s:
                s = self._new()
            s['error'] = None
            try:
                if not isinstance(payload, dict):
                    raise ValueError('Event payload must be an object.')
                if self.inflight and not self.inflight.is_set():
                    raise ValueError('A provider call is still settling. Wait briefly, then Recover; replacement is blocked.')
                pending = self.store.db.execute('SELECT id,session_id FROM operations WHERE result IS NULL').fetchone()
                permitted = event=='memory' or (event=='recover' and pending and pending[1]==s['session_id']) or (event=='approve' and pending and pending[1]==s['session_id'] and payload.get('proposal_id')==pending[0])
                if pending and not permitted:
                    raise ValueError('Recover the pending operation before starting another action.')
                if event == 'new':
                    s = self._new()
                elif event == 'facts':
                    self._facts(s, payload.get('changes'))
                elif event == 'scenario':
                    if payload.get('name') not in SCENARIOS:
                        raise ValueError('Unknown mock scenario.')
                    s['scenario'] = payload['name']
                    self._say(s, 'Mock scenario set to '+s['scenario']+'.')
                elif event == 'select':
                    s['proposal'] = None
                    provider = next((p for p in s['providers'] if p['id'] == payload.get('provider_id')), None)
                    if not provider:
                        raise ValueError('Choose a provider from current results.')
                    self.tools.catalog[provider['id']] = provider
                    provider = self._tool(s, 'get_provider', self.tools.get_provider, provider['id'])
                    slot = canonical_slot(payload.get('slot'))
                    if slot not in provider['free_slots']:
                        raise ValueError('That slot is unavailable.')
                    self.tools.scenario = s['scenario']
                    self.tools.user_id = 'local-user'
                    hold = self._tool(s, 'hold_slot', self.tools.hold_slot, provider['id'], slot)
                    if hold.get('status')=='slot_unavailable':
                        raise ValueError('That slot is unavailable. Choose another provider or slot.')
                    price = hold.pop('quoted_price')
                    if price > s['facts']['budget']:
                        raise ValueError('The exact held quote exceeds your budget. Increase the budget or choose another provider.')
                    self._proposal(s, dict(action='book', provider_id=provider['id'], provider_name=provider['name'], service=provider['service'], slot=slot, price=price, **hold))
                elif event == 'approve':
                    self._approve(s, payload)
                elif event == 'recover':
                    self._recover(s)
                elif event in ('cancel', 'reschedule'):
                    b = next((b for b in self.store.bookings('local-user') if b['id'] == payload.get('booking_id') and b['status']=='booked'), None)
                    if not b:
                        raise ValueError('Choose an active booking in this session.')
                    p = {k:v for k,v in b.items() if k not in ('id','status')}
                    from datetime import timedelta
                    p.update(action=event, booking_id=b['id'], expires_at=(now()+timedelta(minutes=10)).isoformat())
                    if event == 'reschedule':
                        slot = payload.get('slot')
                        try:
                            date = datetime.fromisoformat(slot)
                            if date.tzinfo is None or date <= now():
                                raise ValueError()
                            slot=canonical_slot(slot)
                        except (ValueError, TypeError):
                            raise ValueError('Choose a future ISO slot with a timezone.')
                        p.update(previous_slot=b['slot'], slot=slot)
                    self._proposal(s, p)
                elif event == 'memory':
                    key, op = payload.get('key'), payload.get('op')
                    if op == 'set':
                        self._memory(key, payload.get('value'))
                    elif op == 'confirm':
                        m = next((m for m in self.store.memories() if m['key']==key), None)
                        if not m:
                            raise ValueError('There is no inferred preference to confirm.')
                        self._memory(key, m['value'], m['source'], True)
                    elif op == 'forget':
                        with self.store.db:
                            self.store.db.execute('DELETE FROM memory WHERE key=?', (key,))
                        for (body,) in self.store.db.execute('SELECT body FROM sessions').fetchall():
                            other = json.loads(body)
                            if key in other.get('inherited', []):
                                other['facts'].pop(key, None)
                                other['proposal'] = None
                                other['providers'] = []
                                other['state'] = 'collecting'
                                other['inherited'].remove(key)
                                if other['session_id'] == s['session_id']:
                                    s = other
                                self.store.save(other)
                    else:
                        raise ValueError('Choose set, confirm or forget.')
                    self._say(s, 'Preference '+op+' completed.')
                elif event == 'chat':
                    text = payload.get('text', '')
                    if not isinstance(text, str) or not text.strip() or len(text)>4000:
                        raise ValueError('Please send a message of 1–4000 characters.')
                    s['messages'].append({'role': 'user', 'text': text})
                    if self.model_limit < 1 or time.monotonic()-self.started>=self.wall_limit:
                        raise ValueError('This turn reached its interpreter or wall-clock limit. Please try again.')
                    self._trace(s, 'model', 'offline_interpreter', {'text': text}, {'interpreter_turns': 1, 'tokens': None, 'cost': None, 'availability': 'No external model used'})
                    if text.strip().lower() in ('yes', 'approve', 'confirm') and s['proposal']:
                        self._approve(s, s['proposal'] | {'proposal_id': s['proposal']['id']})
                    elif 'usually' in text.lower() and 'morning' in text.lower():
                        self._memory('earliest_time', '09:00', 'inferred', False)
                        self._say(s, 'I inferred an earliest time of 09:00. Confirm it in Memory before future reuse.')
                    else:
                        changes=interpret(text)
                        active=[b for b in self.store.bookings('local-user') if b['status']=='booked']
                        matching=[b for b in active if not changes.get('service') or b['service']==changes['service']]
                        lower=text.lower()
                        if ('cancel' in lower or any(w in lower for w in ('move my','reschedule'))) and matching:
                            if len(matching)>1:
                                self._say(s,'Choose the booking in Errands so I prepare the correct approval ticket.')
                            elif 'cancel' in lower:
                                self.store.save(s)
                                return self.act(s['session_id'],'cancel',{'booking_id':matching[0]['id']})
                            elif changes.get('date_range'):
                                b=matching[0]
                                candidates=self._tool(s,'search_providers',self.tools.search_providers,b['service'],s['facts'].get('area','local'),changes['date_range'])
                                slot=next((slot for p in candidates for slot in p['free_slots']),None)
                                if not slot:
                                    raise ValueError('No future slot is available for that day. Choose another day.')
                                self.store.save(s)
                                return self.act(s['session_id'],'reschedule',{'booking_id':b['id'],'slot':slot})
                            else:
                                self._say(s,'Which day should I move that booking to? You can also choose a slot in Errands.')
                        else:
                            missing=[k for k in REQUIRED if not s['facts'].get(k)]
                            if not changes and len(missing)>0:
                                if re.fullmatch(r'[\d,]+',text.strip()) and 'budget' in missing:
                                    changes['budget']=int(text.strip().replace(',',''))
                                elif missing[0]=='area' and re.fullmatch(r'[A-Za-z ]{2,80}',text.strip()):
                                    changes['area']=text.strip()
                            if 'same' in lower and ('technician' in lower or 'electrician' in lower):
                                past=self.store.bookings('local-user')
                                if past:
                                    changes['preferred_technician']=past[-1]['provider_name']
                                    self._memory('preferred_technician',past[-1]['provider_name'])
                                else:
                                    self._say(s,'There is no previous technician on record. Tell me a name or choose a provider.')
                            self._facts(s, changes)
                else:
                    raise ValueError('Unsupported event.')
            except (ValueError, KeyError, TypeError) as exc:
                s['error'] = str(exc)
                self._say(s, str(exc))
                self._trace(s, 'notice', 'validation_error', result={'message': str(exc)})
            except Exception:
                s['error'] = 'An unexpected local operation failed. Use Recover before trying a replacement.'
                self._say(s, s['error'])
                self._state(s, 'blocked')
                self._trace(s, 'notice', 'unexpected_failure', result={'message': s['error']})
            self.store.save(s)
            return self.snapshot(s['session_id'])
