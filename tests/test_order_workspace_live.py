import os
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from test_order_workspace import seed_orders
from models import User

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1',reason='Browser opt-in')


def test_order_directory_supplier_history_and_themes(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        supplier,_,_=seed_orders(db,manager.id,ids['site']); supplier_id=supplier.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/ordini')
        expect(page.locator('.order-row')).to_have_count(2)
        page.get_by_label('Cerca ordine o fornitore',exact=True).fill('Riviera')
        page.get_by_role('button',name='Cerca',exact=True).click()
        expect(page.locator('.order-row')).to_have_count(2)
        page.locator('.order-status-card').filter(has_text='Chiusi').click()
        expect(page.locator('.order-row')).to_have_count(1)
        expect(page.get_by_label('Cerca ordine o fornitore',exact=True)).to_have_value('Riviera')
        page.get_by_role('link',name='Azzera',exact=True).click()
        expect(page.locator('.order-row')).to_have_count(2)
        for theme in ['light','dark']:
            if page.locator('html').get_attribute('data-theme') != theme: page.locator('#theme-toggle').click()
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                for path,label in [('/manager/ordini?status=tutti','all'),('/manager/ordini/chiusi','closed'),(f'/manager/fornitori/{supplier_id}#ordini','supplier')]:
                    response=page.goto(origin+path); assert response.status==200
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(path,width)
                    if label=='supplier': page.locator('#ordini').scroll_into_view_if_needed()
                    page.screenshot(path=str(artifacts/f'orders-{label}-{theme}-{width}.png'),full_page=label!='supplier')
        page.set_viewport_size({'width':1440,'height':1000})
        page.goto(origin+f'/manager/fornitori/{supplier_id}#ordini')
        page.get_by_role('link',name='Filtra gli ordini',exact=False).click()
        expect(page.get_by_role('combobox',name='Fornitore',exact=True)).to_have_value(str(supplier_id))
        expect(page.locator('.order-row')).to_have_count(3)
        page.get_by_role('combobox',name='Tipo ordine',exact=True).select_option('closed')
        page.get_by_role('button',name='Cerca',exact=True).click()
        expect(page.locator('.order-row')).to_have_count(1)
        page.locator('.order-open').click();page.wait_for_url('**/manager/ordini/*')
        assert page.locator('.page-title').count()==1
        assert not errors,errors
        print('ORDER_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
