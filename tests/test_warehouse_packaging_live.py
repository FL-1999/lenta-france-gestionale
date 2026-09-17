import os
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import MagazzinoItem, MagazzinoMovimento

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_packaging_preview_save_edit_and_movement(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/magazzino/nuovo')
        expect(page.locator('[data-packaging-fields]')).to_be_hidden()
        page.locator('[name=nome]').fill('Bentonite in sacchi')
        page.locator('[name=packaging_enabled]').check()
        expect(page.locator('[name=unita_misura]')).to_have_value('sacco')
        page.locator('[name=sacchi_per_bancale]').fill('100')
        page.locator('[name=kg_per_sacco]').fill('25')
        page.locator('[name=quantita_disponibile]').fill('2')
        page.locator('[name=stock_unit]').select_option('bancale')
        expect(page.locator('[data-stock-preview]')).to_have_text('2 bancali = 200 sacchi = 5.000 kg')
        for width in [1440,390]:
            page.set_viewport_size({'width':width,'height':1000})
            for theme in ['day','night']:
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(artifacts/f'packaging-new-{theme}-{width}.png'),full_page=True)
                page.locator('#theme-toggle').click()
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url('**/scheda')
        expect(page.locator('#packaging-stock')).to_contain_text('5000')
        with Session(engine) as db:
            item=db.query(MagazzinoItem).filter_by(nome='Bentonite in sacchi').one();item_id=item.id
            assert item.quantita_disponibile==200 and item.sacchi_per_bancale==100 and item.kg_per_sacco==25
        page.screenshot(path=str(artifacts/'packaging-card-mobile.png'),full_page=True)
        page.get_by_role('link',name='Modifica articolo',exact=True).click()
        expect(page.locator('[name=packaging_enabled]')).to_be_checked()
        expect(page.locator('[name=stock_unit]')).to_have_value('sacco')
        expect(page.locator('[data-stock-preview]')).to_have_text('2 bancali = 200 sacchi = 5.000 kg')
        page.get_by_role('button',name='Salva',exact=True).click()
        page.goto(origin+f'/manager/magazzino/items/{item_id}/scheda')
        page.get_by_text('Carichi e prelievi',exact=True).click()
        page.locator('details').filter(has=page.locator('form[action$="/carico-rapido"]')).last.locator(':scope > summary').click()
        form=page.locator('form[action$="/carico-rapido"]')
        form.locator('[name=quantita]').fill('1');form.locator('[name=quantity_unit]').select_option('bancale')
        form.locator('button[type=submit]').click();page.wait_for_url('**/items?ok=carico')
        page.goto(origin+f'/manager/magazzino/items/{item_id}/scheda')
        expect(page.locator('#packaging-stock')).to_contain_text('7500')
        with Session(engine) as db:
            item=db.get(MagazzinoItem,item_id);assert item.quantita_disponibile==300
            assert db.query(MagazzinoMovimento).filter_by(item_id=item_id).count()==2
        assert not errors,errors
        print('PACKAGING_SCREENSHOTS='+str(artifacts))
        browser.close()
