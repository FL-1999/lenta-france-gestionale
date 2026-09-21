import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from tests.test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')

def test_depot_creation_navigation_and_mobile_layout(live_operations):
    origin, engine, ids, password, artifacts=live_operations
    with sync_playwright() as p:
        browser=p.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        page.goto(origin+'/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/depositi/nuovo')
        page.locator('[name=name]').fill('Deposito collaudo')
        page.locator('[name=city]').fill('Nice')
        page.locator('[name=lat]').fill('43.7')
        page.locator('[name=lng]').fill('7.2')
        page.locator('.depot-page button[type=submit]').click()
        page.wait_for_url('**/manager/depositi')
        page.locator('#depot-query').fill('collaudo')
        page.locator('.depot-search button').click()
        expect(page.locator('[data-depot-item]')).to_have_count(1)
        output=Path('.venv/depot-qa');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'list.png'),full_page=True)
        page.get_by_role('link',name='Apri deposito',exact=True).click()
        expect(page.locator('h1')).to_have_text('Deposito collaudo')
        page.locator('#theme-toggle').click()
        page.screenshot(path=str(output/'detail.png'),full_page=True)
        page.get_by_role('link',name='Modifica deposito',exact=True).click()
        page.locator('[name=name]').fill('Deposito aggiornato')
        page.locator('#is_active').select_option('off')
        page.locator('.depot-page button[type=submit]').click()
        page.wait_for_url('**/manager/depositi')
        for path in ['/manager/depositi','/manager/depositi/nuovo']:
            page.goto(origin+path)
            for width in [390,320]:
                page.set_viewport_size({'width':width,'height':850})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(output/('form-mobile.png' if path.endswith('nuovo') else 'list-mobile.png')),full_page=True)
        page.goto(origin+'/manager/cantieri/nuovo')
        expect(page.locator('.cantiere-stepper-item')).to_have_count(3)
        expect(page.get_by_text('Depositi disponibili',exact=True)).to_have_count(0)
        page.locator('#name').fill('Cantiere senza deposito')
        page.locator('#code').fill('DEPOT-QA')
        page.locator('[data-step-action=next]').click()
        expect(page.locator('[data-step="2"]')).to_be_visible()
        page.locator('[data-step-action=next]').click()
        expect(page.locator('[data-step="3"]')).to_be_visible()
        page.locator('.cantiere-mobile-actions button[type=submit]').click()
        page.wait_for_url('**/manager/cantieri')
        browser.close()
