"""Execute real scripted-user tests and emit machine-readable evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from errand.agent import Agent
from errand.tools import TZ


class Results(unittest.TextTestResult):
    def startTest(self, test):
        name=test.id().split('.')[-1]
        self.rows.append({'scenario': name, 'expected': EXPECTED.get(name,'All named behavioral assertions hold.'), 'actual':None, 'passed': True,'notes':'Offline stdlib test; isolated temporary SQLite database.'})
        super().startTest(test)

    def addFailure(self, test, err):
        self.rows[-1]['passed'] = False
        self.rows[-1]['actual'] = self._exc_info_to_string(err,test)
        super().addFailure(test, err)

    def addError(self, test, err):
        self.rows[-1]['passed'] = False
        self.rows[-1]['actual'] = self._exc_info_to_string(err,test)
        super().addError(test, err)

    def addSuccess(self,test):
        s=test.final_snapshot
        self.rows[-1]['actual']=f"Assertions passed; state={s['state']}; bookings={len(s['bookings'])}; proposal={s['proposal']['action'] if s['proposal'] else 'none'}; error={s['error']!r}"
        super().addSuccess(test)

    def __init__(self, *args):
        super().__init__(*args)
        self.rows = []


EXPECTED = {
 'test_equivalent_slot_encodings_cannot_bypass_occupancy':'UTC and zero-fraction ISO variants of occupied instant all conflict and preserve original slot.',
 'test_reschedule_proposal_canonicalizes_offset':'Reschedule ticket normalizes equivalent aware ISO timestamp to +05:30 canonical slot.',
 'test_distinct_holds_cannot_double_book_provider_slot':'Two holds/keys cannot book one provider slot; occupied availability disappears.',
 'test_reschedule_actual_occupied_slot_preserves_original':'Actual occupied target returns conflict and leaves original booking unchanged.',
 'test_optional_fact_clear':'Explicit null removes optional earliest time and technician facts.',
 'test_not_before_dotted_time':'Not-before dotted a.m. syntax maps to exact earliest time.',
 'test_any_time_clears_earliest':'Explicit any-time correction removes old earliest constraint.',
 'test_slow_read_hard_deadline':'Deliberately slow provider read returns user-facing deadline error within cap.',
 'test_slow_mutation_reconciles_before_replacement':'Slow mutation returns within deadline, blocks replacement, then reconciles one late booking.',
 'test_unsupported_date_does_not_silently_book_tomorrow':'Unsupported date returns user error without fabricated tomorrow availability.',
 'test_trace_runs_persist_beyond_snapshot':'Trace events remain queryable by run ID after reopening SQLite.',
 'test_other_prepared_approval_blocked_while_pending':'A pre-existing proposal in another session cannot execute during unresolved operation.',
 'test_completed_operation_reconstructs_receipt':'Recovery rebuilds final receipt from completed durable operation.',
 'test_bookings_visible_in_new_errand':'One booked receipt remains visible in another errand.',
 'test_cancel_retries':'Cancellation needs approval, retries initial 503 once and ends cancelled.',
 'test_cancel_retry_exhaustion':'Repeated 503 produces error while original booking stays booked.',
 'test_chat_cancel_prepares_approval':'User cancellation chat prepares cancel ticket without mutation.',
 'test_chat_reschedule_prepares_approval':'Move-to-Saturday chat prepares reschedule ticket.',
 'test_collects_missing':'Plumber maps to plumbing and creates no booking.',
 'test_cross_session_approval_rejected':'A proposal from another session cannot be approved.',
 'test_edit_invalidates':'Budget edit invalidates the prior approval.',
 'test_empty_area_rejected':'Whitespace area returns validation error.',
 'test_engine_model_limit':'Zero interpreter budget rejects chat with user error.',
 'test_engine_wall_limit':'Zero wall budget rejects search with user error.',
 'test_fixed_provider_contract':'Eight-tool contract supplies providers/details/quote, idempotent booking and status.',
 'test_forget_preserves_pending_recovery':'Forgetting memory does not prevent durable approved-operation recovery.',
 'test_hold_expiry':'Expired ten-minute hold cannot execute.',
 'test_http_transport_guards':'State GET succeeds; external Origin receives 403; traversal receives 404.',
 'test_inferred_needs_confirmation':'Inferred preference remains unconfirmed and is not inherited.',
 'test_injection_ignored':'Provider injection text is present as data and causes no booking.',
 'test_invalid_event_message':'Unknown event returns error and assistant message.',
 'test_limit':'Configured exhaustion produces a user-visible failure.',
 'test_memory_forget':'Confirmed area inherits, then forget removes inherited active fact.',
 'test_memory_set_validates_time':'99:99 memory is rejected.',
 'test_missing_fact_conversation':'Four natural user messages fill missing facts and reach choosing.',
 'test_mutated_hold_rejected':'Actual durable held-price mutation invalidates approval before booking.',
 'test_next_week_slots_match_request':'Next-week availability occurs seven days from local current day.',
 'test_preferred_technician_constraint':'Search offers only the exact named technician.',
 'test_price_change':'Ticket uses held quote rather than search price and approves exact higher quote.',
 'test_quote_over_budget_rejected':'A held quote over budget creates no approval proposal.',
 'test_receipt_booking_id':'Completed proposal receipt contains authoritative booking ID.',
 'test_repeat_is_idempotent':'Repeated exact approval results in one booking.',
 'test_reschedule_conflict':'Configured slot conflict preserves original booking slot.',
 'test_restart_pending':'Reopening real SQLite after provider commit recovers exactly one booking.',
 'test_single_interpreter_turn':'One chat produces exactly one interpreter event.',
 'test_slot_taken':'Taken slot produces no booking.',
 'test_slot_unavailable':'Unavailable hold produces user error.',
 'test_stale_fingerprint':'Forged fingerprint is rejected.',
 'test_starter_conversations':'All three UI prompts extract service, comma INR budget and required facts.',
 'test_success_requires_approval':'Selection alone does not book; approved exact ticket completes.',
 'test_time_change_invalidates':'Time-window edit invalidates old exact approval.',
 'test_timeout_after_success':'Timeout is reconciled by authoritative status and exactly one booking.',
 'test_timeout_not_booked':'Authoritative failed timeout produces no booking.',
 'test_tool_call_cap':'Ninth tool attempt is rejected by engine cap.',
 'test_unknown_error_blocks':'Unresolved provider result blocks replacement.',
 'test_unknown_exception_has_message':'Unexpected exception produces sanitized user-facing error.',
 'test_wall_time_cap':'Tool attempt after elapsed wall deadline is rejected.'
}


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2, resultclass=Results).run(unittest.defaultTestLoader.discover('tests', pattern='test_agent.py'))
    out = Path('output')
    out.mkdir(exist_ok=True)
    (out/'eval-results.json').write_text(json.dumps(result.rows, indent=2))
    def cell(value):
        return str(value).replace('|','/').replace('\n',' ')
    (out/'eval-results.md').write_text('| Scenario | Expected | Actual | Pass/fail | Notes |\n|---|---|---|---|---|\n'+'\n'.join('| '+' | '.join(cell(v) for v in (r['scenario'],r['expected'],r['actual'],'PASS' if r['passed'] else 'FAIL',r['notes']))+' |' for r in result.rows)+'\n')
    fixed=datetime(2026,10,31,9,0,tzinfo=TZ)
    with tempfile.TemporaryDirectory() as tmp, patch('errand.tools.now',return_value=fixed), patch('errand.agent.now',return_value=fixed):
        a = Agent(str(Path(tmp)/'trace.db'))
        sid = a.snapshot()['session_id']
        a.act(sid, 'scenario', {'name':'timeout_after_success'})
        s = a.act(sid, 'facts', {'changes':dict(service='plumbing',area='Indiranagar',date_range='tomorrow',time_window='morning',budget=2000)})
        p = s['providers'][0]
        s = a.act(sid, 'select', {'provider_id':p['id'],'slot':p['free_slots'][0]})
        p = s['proposal']
        s = a.act(sid, 'approve', {'proposal_id':p['id'],'fingerprint':p['fingerprint']})
        (out/'timeout-after-success-trace.json').write_text(json.dumps(s, indent=2))
        a.close()
    raise SystemExit(0 if result.wasSuccessful() else 1)
