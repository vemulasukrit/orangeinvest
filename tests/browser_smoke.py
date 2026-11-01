"""Live UI checks. Optional test dependency: pip install playwright.
Uses installed Chrome so the application itself has no browser dependency.
Start an isolated server first: python server.py --db .data/ui-test.db --port 8766
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run(url, screenshot_only=False):
    out = Path('output')
    out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto(url)
        page.wait_for_load_state('networkidle')
        expect(page.get_by_role('heading', name='Consider it done.')).to_be_visible()
        expect(page.locator('.ticket-empty')).to_be_visible()
        page.screenshot(path=str(out / 'desktop.png'), full_page=True, animations="disabled")
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(out / 'mobile.png'), full_page=True, animations="disabled")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
        page.set_viewport_size({'width':1440,'height':1100})
        if not screenshot_only:
            page.get_by_role('button', name='A tap that won’t stop dripping').click()
            expect(page.locator('.provider')).to_have_count(4)
            expect(page.locator('#ticket-state')).to_have_text('Your choice')
            page.locator('[data-select-provider]').first.click()
            expect(page.get_by_role('button', name='Approve & book')).to_be_visible()
            page.screenshot(path=str(out / 'review.png'), full_page=True, animations="disabled")
            page.get_by_role('button', name='Activity', exact=True).click()
            page.locator('#scenario-select').select_option('timeout_after_success')
            page.get_by_role('button', name='Use this scenario').click()
            expect(page.locator('.scenario-active')).to_contain_text('Timeout after success')
            page.get_by_role('button', name='Approve & book').click()
            expect(page.locator('#ticket-state')).to_have_text('Verified')
            expect(page.locator('.receipt-status')).to_contain_text('Booking confirmed')
            expect(page.locator('#trace-list')).to_contain_text('get_booking_status')
            page.screenshot(path=str(out / 'recovery.png'), full_page=True, animations="disabled")
            page.locator('#close-panel').click()
            page.locator('#composer-input').fill('yes')
            page.get_by_role('button', name='Send request').click()
            expect(page.locator('#booking-count')).to_have_text('1')
            page.reload()
            expect(page.locator('#booking-count')).to_have_text('1')
            page.get_by_role('button', name='Memory', exact=True).click()
            page.locator('#memory-form [name="value"]').fill('Whitefield')
            page.get_by_role('button', name='Save preference').click()
            expect(page.locator('.memory-row')).to_contain_text('Whitefield')
            page.get_by_role('button', name='Forget', exact=True).click()
            expect(page.locator('.memory-row')).to_have_count(0)
            page.locator('#close-panel').click()
            page.get_by_role('button', name='Your errands', exact=False).first.click()
            page.get_by_role('button', name='Cancel this errand').click()
            expect(page.get_by_role('button', name='Confirm cancellation')).to_be_visible()
            page.get_by_role('button', name='Confirm cancellation').click()
            expect(page.locator('.receipt-status')).to_contain_text('Cancellation confirmed')
        assert not errors, errors
        browser.close()
        print('PASS: desktop/mobile layout, live booking, timeout reconciliation, repeat confirmation, reload, memory forget, cancellation; no browser errors.' if not screenshot_only else 'PASS: initial layout and no browser errors.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8766')
    parser.add_argument('--screenshot-only', action='store_true')
    args = parser.parse_args()
    run(args.url, args.screenshot_only)
