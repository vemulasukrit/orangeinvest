"""Behavioral regressions for the presentation revision; optional Playwright tooling."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from errand.agent import Agent
from server import handler
from playwright.sync_api import sync_playwright, expect


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = Agent(str(Path(self.tmp.name) / 'ui.db'))
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.agent))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.context = self.browser.new_context(viewport={'width':1440,'height':1000})
        self.page = self.context.new_page()
        self.page.goto(f'http://127.0.0.1:{self.http.server_port}')
        self.page.wait_for_function('state !== null')

    def tearDown(self):
        self.context.close()
        self.http.shutdown()
        self.http.server_close()
        self.agent.close()
        self.tmp.cleanup()

    def action(self,event,payload=None):
        return self.page.evaluate('([event,payload]) => request(event,payload)',[event,payload or {}])

    def choose(self):
        self.action('scenario',{'name':'success'})
        snapshot=self.action('facts',{'changes':{'service':'plumbing','area':'Indiranagar','date_range':'tomorrow','time_window':'morning','budget':1500}})
        p=snapshot['providers'][0]
        return self.action('select',{'provider_id':p['id'],'slot':p['free_slots'][0]})

    def test_activity_does_not_move_ticket_or_hide_navigation(self):
        before=self.page.locator('#ticket').bounding_box()
        self.page.get_by_role('button',name='Activity',exact=True).click()
        self.page.wait_for_timeout(400)
        after=self.page.locator('#ticket').bounding_box()
        self.assertLess(abs(before['x']-after['x']),2,'Opening activity moved the service ticket')
        expect(self.page.get_by_role('button',name='Activity',exact=True)).to_be_visible()

    def test_existing_messages_keep_their_dom_identity(self):
        self.page.evaluate('window.firstMessage = document.querySelector(".message")')
        self.action('chat',{'text':'I need a plumber'})
        self.assertTrue(self.page.evaluate('firstMessage.isConnected'),'Every reply destroys the conversation DOM')

    def test_receipt_retains_the_approved_price(self):
        snapshot=self.choose()
        p=snapshot['proposal']
        self.action('approve',{'proposal_id':p['id'],'fingerprint':p['fingerprint']})
        expect(self.page.locator('.receipt-status')).to_contain_text('Booking confirmed')
        self.assertIn('₹600',self.page.locator('#ticket').inner_text(),'Receipt loses the price after approval')

    def test_provider_choice_is_in_the_working_area(self):
        self.choose()
        self.assertTrue(self.page.evaluate('document.querySelector(".conversation").contains(document.querySelector("#provider-section"))'),'Provider choices push the entire page below the ticket')

    def test_ticket_transition_animates_and_honors_reduced_motion(self):
        self.choose()
        active=self.page.evaluate('document.querySelector("#ticket").getAnimations({subtree:true}).length')
        self.assertGreater(active,0,'Ticket replacement has no progressive transition')
        self.page.emulate_media(reduced_motion='reduce')
        self.action('facts',{'changes':{'budget':1800}})
        active=self.page.evaluate('document.querySelector("#ticket").getAnimations({subtree:true}).length')
        self.assertEqual(active,0,'Motion preference is ignored')

    def test_failed_chat_does_not_remain_as_sent(self):
        self.page.route('**/api/action',lambda route:route.abort())
        self.action('chat',{'text':'This request cannot reach the server'})
        expect(self.page.locator('.message.user')).to_have_count(0)
        expect(self.page.locator('#toast')).to_be_visible()
        expect(self.page.locator('#suggestions')).to_be_visible()

    def test_long_review_does_not_overlap_progress(self):
        self.page.set_viewport_size({'width':800,'height':900})
        self.choose()
        # Exercise legal long content and the longer reschedule review state.
        self.page.evaluate('''() => {
          state.proposal.action='reschedule';
          state.proposal.area='Indiranagar, near the community centre and the east entrance';
          renderTicket();
          document.querySelector('#ticket').getAnimations({subtree:true}).forEach(a=>a.finish());
        }''')
        bottom=self.page.locator('.ticket-bottom').bounding_box()
        journey=self.page.locator('.journey').bounding_box()
        self.assertLessEqual(bottom['y']+bottom['height'],journey['y'])
        self.assertTrue(self.page.evaluate('''() => {
          const s=document.querySelector('.ticket-stage');
          return s.scrollHeight<=s.clientHeight || getComputedStyle(s).overflowY==='auto';
        }'''))
        self.page.locator('.ticket-stage').evaluate('(el)=>el.scrollTop=el.scrollHeight')
        self.page.get_by_role('button',name='Activity',exact=True).click()
        self.assertEqual(self.page.locator('.ticket-stage').evaluate('(el)=>el.scrollTop'),0)


if __name__=='__main__':
    unittest.main(verbosity=2)
