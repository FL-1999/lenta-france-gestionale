import os
from datetime import date
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from models import Fiche, User, Supplier, CostDelivery, CostInvoice
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_live_costs_fiche_tickets_invoice_and_mobile(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        supplier=Supplier(name='Centrale Collaudo');db.add(supplier);db.flush();sid=supplier.id
        fiche=Fiche(site_id=ids['site'],created_by_id=manager.id,fiche_type='produzione',description='Getto',
            numero_pannello=1,panel_name='P1',date=date(2026,9,24),data_getto=date(2026,9,24),tipologia_scavo='paratia',metri_cubi_gettati=26)
        db.add(fiche);db.commit();fid=fiche.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/costi')
        expect(page.get_by_role('heading',name='Costi e consegne',exact=True)).to_be_visible()
        page.locator('[data-tab=contracts]').click()
        editor=page.locator('#contract-editor')
        editor.locator('[name=name]').fill('C30 Collaudo');editor.locator('[name=supplier_id]').select_option(str(sid))
        editor.locator('[name=price]').fill('100');editor.locator('[name=surcharge]').select_option('fixed');editor.locator('[name=rate]').fill('50')
        page.locator('#save-contract').click();expect(page.locator('#cost-message')).to_contain_text('Salvato')
        page.locator('[data-tab=deliveries]').click();page.locator('[data-source]').click()
        rows=page.locator('#delivery-lines tr');expect(rows).to_have_count(4)
        assert [rows.nth(i).locator('[name=quantity]').input_value() for i in range(4)]==['7.5','7.5','7.5','3.5']
        for i in range(4):rows.nth(i).locator('[name=ticket]').fill(f'BL-{i+1}')
        rows.nth(3).locator('[name=quantity]').fill('3')
        page.locator('#save-delivery').click();expect(page.get_by_role('alert')).to_contain_text('scegli se aggiornarla')
        expect(rows.nth(0).locator('[name=ticket]')).to_have_value('BL-1')
        page.locator('[name=fiche-choice][value=update]').check();page.locator('#save-delivery').click()
        expect(page.locator('#cost-message')).to_contain_text('Salvato')
        with Session(engine) as db:assert db.get(Fiche,fid).metri_cubi_gettati==25.5
        page.locator('[data-tab=invoices]').click();page.locator('#invoice-supplier').select_option(str(sid))
        invoice_rows=page.locator('#invoice-candidates tr[data-line]');expect(invoice_rows).to_have_count(4)
        for i in range(4):invoice_rows.nth(i).locator('[name=selected]').check()
        page.locator('[name=invoice-number]').fill('F-09');page.locator('[name=invoice-total]').fill('2601')
        page.locator('#invoice-confirm').check();page.locator('#save-invoice').click()
        expect(page.get_by_role('alert')).to_contain_text('non coincide')
        page.locator('[name=invoice-total]').fill('2600');page.locator('#save-invoice').click();expect(page.locator('#cost-message')).to_contain_text('Salvato')
        expect(page.get_by_text('F-09 · Centrale Collaudo',exact=False)).to_be_visible()
        page.locator('[data-tab=shared]').click();page.locator('[name=description]').fill('Transport essai')
        page.locator('[name=total]').fill('900');page.locator('[name=weight]').fill('2');page.locator('#add-allocation').click()
        page.locator('#allocation-rows [name=site_id]').nth(1).select_option(str(ids['other']))
        page.locator('#split-allocation').click();expect(page.locator('#allocation-rows [name=amount]').first).to_have_value('600')
        page.locator('#save-shared').click();expect(page.locator('#cost-message')).to_contain_text('Salvato')
        for theme in ['dark','light']:
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000})
                for tab in ['overview','deliveries','contracts','invoices','shared']:
                    page.locator(f'[data-tab={tab}]').click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),(theme,width,tab)
                page.screenshot(path=str(artifacts/f'costs-{theme}-{width}.png'),full_page=True)
        context.add_cookies([{'name':'lang','value':'fr','url':origin}]);page.reload()
        expect(page.get_by_role('heading',name='Coûts et livraisons',exact=True)).to_be_visible()
        page.locator('[data-tab=deliveries]').click();expect(page.get_by_role('heading',name='Registre vérifié')).to_be_visible()
        assert not errors
        browser.close()
    with Session(engine) as db:
        assert db.query(CostInvoice).one().total==2600
        assert db.query(CostDelivery).one().economic_entry.amount==2600
