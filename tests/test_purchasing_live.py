import os
from pathlib import Path
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import Supplier, SupplierContact, MagazzinoCategoria, MagazzinoItem, PurchaseOrder

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')

def test_supplier_order_partial_and_final_receipt_in_browser(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        category=MagazzinoCategoria(nome='Bulloneria',slug='bulloneria',attiva=True)
        db.add(category);db.commit();cat_id=category.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        page=context.new_page();errors=[];failures=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.on('response',lambda r: failures.append(r.url) if r.status>=500 else None)
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/fornitori/nuovo')
        page.locator('input[name=name]').fill('Mario Collaudo')
        page.locator('input[name=email]').fill('mario@example.com')
        page.get_by_role('button',name='Salva',exact=True).click()
        page.wait_for_url('**/manager/fornitori/*')
        for name in ['Maria acquisti','Luca consegne']:
            details=page.locator('#new-contact');details.evaluate('(el)=>el.open=true')
            details.locator('input[name=name]').fill(name)
            details.locator('input[name=email]').fill('referente@example.com')
            details.get_by_role('button',name='Aggiungi referente').click()
            page.wait_for_load_state('networkidle')
        supplier_url=page.url
        with Session(engine) as db:
            supplier_id=db.query(Supplier).filter_by(name='Mario Collaudo').one().id
            contact_id=db.query(SupplierContact).filter_by(name='Maria acquisti').one().id
        page.screenshot(path=str(artifacts/'supplier-desktop.png'),full_page=True)
        page.goto(origin+'/manager/magazzino/nuovo')
        page.locator('input[name=nome]').fill('Bullone M12')
        page.locator('select[name=categoria_id]').select_option(str(cat_id))
        page.get_by_role('button',name='Salva',exact=True).click()
        page.wait_for_url('**/scheda')
        page.locator('select[name=supplier_id]').select_option(str(supplier_id))
        page.locator('input[name=code]').fill('678')
        page.get_by_role('button',name='Collega fornitore').click()
        page.wait_for_load_state('networkidle')
        page.goto(origin+f'/manager/ordini/nuovo?supplier_id={supplier_id}')
        expect(page.locator('#supplier-contact-select option')).to_have_count(3)
        page.locator('#supplier-contact-select').select_option(str(contact_id))
        expect(page.locator('#supplier-codes-list option')).to_have_count(1)
        page.locator('[data-codice]').fill('678')
        expect(page.locator('[data-desc]')).to_have_value('Bullone M12')
        page.locator('input[name=qty_ordered]').fill('10')
        page.get_by_role('button',name='Crea ordine',exact=True).click()
        page.wait_for_url('**/manager/ordini/*')
        with Session(engine) as db: order_id=db.query(PurchaseOrder).one().id
        assert page.url.endswith('/'+str(order_id))
        for number,qty in [('BL-1','4'),('BL-2','6')]:
            page.get_by_role('link',name='Nuova bolla',exact=False).click()
            page.locator('input[name=delivery_number]').fill(number)
            page.locator('input[name=qty_delivered]').fill(qty)
            page.get_by_role('button',name='Conferma ricezione').click()
            page.wait_for_url('**/manager/ordini/'+str(order_id))
        expect(page.locator('.page-subtitle')).to_contain_text('CHIUSO')
        expect(page.locator('main')).to_contain_text('BL-1');expect(page.locator('main')).to_contain_text('BL-2')
        page.screenshot(path=str(artifacts/'order-received-desktop.png'),full_page=True)
        page.locator('#theme-toggle').click()
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        page.screenshot(path=str(artifacts/'order-received-night.png'),full_page=True)
        with Session(engine) as db: assert db.query(MagazzinoItem).one().quantita_disponibile==10
        page.set_viewport_size({'width':390,'height':844})
        for path in [f'/manager/fornitori/{supplier_id}',f'/manager/ordini/nuovo?supplier_id={supplier_id}',f'/manager/ordini/{order_id}']:
            page.goto(origin+path)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),path
        page.screenshot(path=str(artifacts/'order-received-mobile.png'),full_page=True)
        assert not errors,errors
        assert not failures,failures
        print('PURCHASING_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
