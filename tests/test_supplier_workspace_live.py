import os
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import Supplier, SupplierContact

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1',reason='Browser opt-in')


def test_supplier_material_cards_and_code_correction(live_operations):
    from models import MagazzinoItem,SupplierArticle,PurchaseOrder,PurchaseOrderLine,PurchaseDelivery,PurchaseDeliveryLine
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        supplier=Supplier(name='Forniture collaudo',is_active=True)
        item=MagazzinoItem(nome='Gancio automatico D13',unita_misura='pz',attivo=True,quantita_disponibile=4)
        db.add_all([supplier,item]);db.flush()
        article=SupplierArticle(supplier_id=supplier.id,codice='ERRATO-13',descrizione=item.nome,magazzino_item_id=item.id)
        po=PurchaseOrder(supplier_id=supplier.id,order_number='TEST-ACQUISTI');db.add_all([article,po]);db.flush()
        line=PurchaseOrderLine(order_id=po.id,magazzino_item_id=item.id,codice='ERRATO-13',qty_ordered=10)
        delivery=PurchaseDelivery(order_id=po.id,delivery_number='BL-TEST',confirmed=True,delivery_type='PICKUP')
        db.add_all([line,delivery]);db.flush();db.add(PurchaseDeliveryLine(delivery_id=delivery.id,order_line_id=line.id,qty_delivered=4))
        db.commit();supplier_id=supplier.id;item_id=item.id;article_id=article.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        profile=origin+f'/manager/fornitori/{supplier_id}'
        page.goto(profile)
        expect(page.locator('.supplier-material-quantities dd')).to_have_text(['10 pz','4 pz','6 pz'])
        for theme in ['light','dark']:
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000})
                page.locator('#acquisti').scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(artifacts/f'supplier-materials-{theme}-{width}.png'))
        page.locator('#articoli').get_by_role('link',name='Modifica codice',exact=True).click()
        page.locator('input[name=code]').fill('2CLC3')
        expect(page.locator('[data-purchase-return]')).to_have_attribute('href',f'/manager/fornitori/{supplier_id}')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(artifacts/'supplier-code-mobile.png'),full_page=True)
        page.get_by_role('button',name='Salva codice',exact=True).click();page.wait_for_url('**/fornitori/*?saved=code#articoli')
        expect(page.locator('#articoli .warehouse-code')).to_have_text('2CLC3')
        expect(page.locator('.supplier-material-codes')).to_contain_text('ERRATO-13')
        page.goto(origin+f'/manager/magazzino/items/{item_id}/scheda')
        page.locator('#fornitori').get_by_role('link',name='Modifica codice',exact=True).click()
        expect(page.locator('input[name=code]')).to_have_value('2CLC3')
        page.get_by_role('link',name='Annulla',exact=True).click()
        assert not errors,errors
        context.close();browser.close()
    with Session(engine) as db:
        assert db.get(SupplierArticle,article_id).codice=='2CLC3'
        assert db.query(PurchaseOrderLine).one().codice=='ERRATO-13'

def test_supplier_directory_profile_contacts_and_themes(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        supplier=Supplier(name='Méditerranée Fournitures',email='commandes@example.com',phone='+33 4 00 00 00 00',city='Nice',country='France',address='Adresse de démonstration',is_active=True)
        inactive=Supplier(name='Archive démonstration',is_active=False)
        db.add_all([supplier,inactive]);db.flush()
        db.add_all([SupplierContact(supplier_id=supplier.id,name='Marie Achats',email='marie@example.com',role_label='Commercial'),SupplierContact(supplier_id=supplier.id,name='Paul Livraison',email='paul@example.com',role_label='Livraisons')]);db.commit();supplier_id=supplier.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[];failures=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:failures.append(r.url) if r.status>=500 else None)
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/fornitori')
        expect(page.locator('.supplier-row')).to_have_count(2)
        page.get_by_label('Cerca fornitore',exact=True).fill('Marie')
        page.get_by_role('button',name='Cerca',exact=True).click()
        expect(page.locator('.supplier-row')).to_have_count(1)
        page.screenshot(path=str(artifacts/'suppliers-day.png'),full_page=True)
        page.locator('#theme-toggle').click()
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        page.screenshot(path=str(artifacts/'suppliers-night.png'),full_page=True)
        page.get_by_role('link',name='Apri scheda',exact=False).click()
        expect(page.locator('.page-title')).to_have_text('Méditerranée Fournitures')
        page.get_by_text('Modifica dati aziendali',exact=True).click()
        page.locator('#supplier-city').fill('Antibes')
        page.locator('#supplier-profile-form').get_by_role('button',name='Salva',exact=True).click()
        expect(page.locator('.supplier-profile-summary')).to_contain_text('Antibes')
        contact=page.locator('.supplier-contact-editor').filter(has_text='Marie Achats')
        contact.locator('summary').click()
        contact.locator('input[name=phone]').fill('+33 6 11 22 33 44')
        contact.get_by_role('button',name='Salva referente').click()
        page.wait_for_load_state('networkidle')
        with Session(engine) as db:
            assert db.query(SupplierContact).filter_by(name='Marie Achats').one().phone=='+33 6 11 22 33 44'
        page.screenshot(path=str(artifacts/'supplier-profile-night.png'),full_page=True)
        page.get_by_role('link',name='Nuovo ordine',exact=False).click()
        expect(page.locator('#supplier-contact-select option')).to_have_count(3)
        page.goto(origin+f'/manager/fornitori/{supplier_id}')
        page.locator('#theme-toggle').click()
        page.screenshot(path=str(artifacts/'supplier-profile-day.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        for path in ['/manager/fornitori',f'/manager/fornitori/{supplier_id}','/manager/fornitori/nuovo']:
            page.goto(origin+path)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),path
        page.goto(origin+f'/manager/fornitori/{supplier_id}')
        page.screenshot(path=str(artifacts/'supplier-profile-mobile.png'),full_page=True)
        page.locator('.supplier-management > summary').click()
        page.get_by_role('button',name='Disattiva fornitore',exact=True).click()
        page.get_by_role('link',name='Disattivi',exact=False).click()
        expect(page.locator('.supplier-row')).to_have_count(2)
        assert not errors,errors
        assert not failures,failures
        print('SUPPLIER_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
