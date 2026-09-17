import os
import pytest
from playwright.sync_api import expect,sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import MagazzinoItem,MagazzinoCategoria,MagazzinoMacro,Supplier,SupplierArticle,PurchaseOrder,Site

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_mixed_order_rows_and_site_selection_in_browser(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        macro=MagazzinoMacro(name='Accessori sollevamento');db.add(macro);db.flush()
        cat=MagazzinoCategoria(nome='Ganci',slug='ganci',macro_id=macro.id,attiva=True)
        item=MagazzinoItem(nome='Gancio esistente',categoria=cat,quantita_disponibile=0,attivo=True)
        supplier=Supplier(name='Fornitore collaudo',is_active=True)
        db.add_all([item,supplier,Site(name='Cantiere archiviato',is_active=False)]);db.flush()
        db.add(SupplierArticle(supplier_id=supplier.id,codice='KNOWN',magazzino_item_id=item.id));db.commit()
        supplier_id,cat_id,macro_id,item_id=supplier.id,cat.id,macro.id,item.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[];failures=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:failures.append(r.url) if r.status>=500 else None)
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/ordini/nuovo?supplier_id={supplier_id}')
        expect(page.locator('#supplier-codes-list option')).to_have_count(1)
        rows=page.locator('#order-lines [data-order-line]')
        row=rows.nth(0);row.locator('[data-codice]').fill('KNOWN')
        expect(row.locator('[name=magazzino_item_id]')).to_have_value(str(item_id))
        expect(row.locator('[data-existing-classification]')).to_contain_text('Accessori sollevamento / Ganci')
        row.locator('[name=qty_ordered]').fill('2')
        for i,mode,name,code,unit in [(1,'existing','Gancio nuovo','HOOK','pz'),(2,'new_in_macro','Catena','CHAIN','m'),(3,'new_macro','Olio','OIL','l')]:
            page.locator('#add-row').click();row=rows.nth(i)
            row.locator('[data-codice]').fill(code)
            row.locator('[name=magazzino_item_id]').select_option('__new__')
            expect(row.locator('[data-codice]')).to_have_value(code)
            row.locator('[name=description]').fill(name);row.locator('[name=qty_ordered]').fill('4')
            row.locator('[name=line_category_mode]').select_option(mode)
            row.locator('[name=line_unit]').select_option(unit)
            if mode=='existing':row.locator('[name=line_category_id]').select_option(str(cat_id))
            elif mode=='new_in_macro':
                row.locator('[name=line_macro_id]').select_option(str(macro_id));row.locator('[name=line_new_category]').fill('Catene')
            else:
                row.locator('[name=line_new_macro]').fill('Lubrificanti');row.locator('[name=line_new_category]').fill('Oli')
        # Reordering the submitted arrays by deleting an intermediate row must stay aligned.
        page.locator('#add-row').click();rows.nth(4).get_by_role('button',name='Rimuovi riga').click()
        expect(rows).to_have_count(4)
        page.locator('input[name=order_kind][value=closed]').check()
        expect(page.locator('#order-site')).to_be_visible()
        expect(page.locator('#order-site option')).to_have_count(3)
        expect(page.locator('#order-site')).not_to_contain_text('Cantiere archiviato')
        page.locator('#order-site').select_option(str(ids['other']))
        for theme in ['light','dark']:
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            page.screenshot(path=str(artifacts/f'order-mixed-{theme}.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(artifacts/'order-mixed-mobile.png'),full_page=True)
        # Simulate a catalog edit while this form is open, then repair and resubmit.
        with Session(engine) as db:db.get(MagazzinoCategoria,cat_id).attiva=False;db.commit()
        page.get_by_role('button',name='Crea ordine',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Riga 2')
        expect(rows.nth(2).locator('[name=line_new_category]')).to_have_value('Catene')
        expect(rows.nth(3).locator('[name=line_new_macro]')).to_have_value('Lubrificanti')
        expect(rows.nth(1).locator('[data-codice]')).to_have_value('HOOK')
        expect(page.locator('#order-site')).to_have_value(str(ids['other']))
        # Choose a valid new category on that row without losing the other rows.
        rows.nth(1).locator('[name=line_category_mode]').select_option('new_in_macro')
        rows.nth(1).locator('[name=line_macro_id]').select_option(str(macro_id))
        rows.nth(1).locator('[name=line_new_category]').fill('Ganci nuovi')
        page.get_by_role('button',name='Crea ordine',exact=True).click()
        page.wait_for_url('**/manager/ordini/*')
        assert '/nuovo' not in page.url
        with Session(engine) as db:
            order=db.query(PurchaseOrder).one()
            assert order.site_id==ids['other'] and order.delivery_site_id==ids['other']
            assert len(order.lines)==4 and db.query(MagazzinoItem).count()==4
            assert [line.magazzino_item.unita_misura for line in order.lines]==['pz','pz','m','l']
        page.goto(origin+f'/manager/ordini/nuovo?supplier_id={supplier_id}')
        expect(page.locator('#closed-section')).to_be_hidden()
        assert page.locator('#order-site').get_attribute('required') is None
        assert not errors,errors
        assert not failures,failures
        print('MIXED_ORDER_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
