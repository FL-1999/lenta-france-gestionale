import os
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from test_order_workspace import seed_orders
from models import User, MagazzinoItem, SupplierArticle

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1',reason='Browser opt-in')


def test_navigation_b_preserves_context_filters_and_role_boundaries(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        supplier,_,orders=seed_orders(db,manager.id,ids['site'])
        item=MagazzinoItem(nome='Gancio navigazione',quantita_disponibile=4,attivo=True)
        db.add(item);db.flush();db.add(SupplierArticle(supplier_id=supplier.id,codice='NAV-01',magazzino_item_id=item.id))
        orders[1].lines[0].magazzino_item_id=item.id;db.commit()
        supplier_id,item_id,order_id=supplier.id,item.id,orders[1].id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        listing=origin+f'/manager/ordini?status=parziale&q=Riviera&supplier_id={supplier_id}'
        page.goto(listing)
        expect(page.locator('main .warehouse-toolbar')).to_have_count(0)
        expect(page.locator('[data-purchase-section][aria-current=page]')).to_have_attribute('data-purchase-section','orders')
        page.locator('.order-open').click()
        expect(page.locator('[data-purchase-return]')).to_have_attribute('href',listing.replace(origin,''))
        page.locator(f'main a[href$="/manager/fornitori/{supplier_id}"]').click()
        expect(page.locator('[data-purchase-section][aria-current=page]')).to_have_attribute('data-purchase-section','suppliers')
        page.locator(f'#articoli a[href$="/items/{item_id}/scheda"]').click()
        expect(page.locator('[data-purchase-return]')).to_contain_text('Riviera Fournitures')
        page.reload()
        expect(page.locator('[data-purchase-return]')).to_contain_text('Riviera Fournitures')
        page.locator('[data-purchase-return]').click();page.wait_for_url(f'**/fornitori/{supplier_id}')
        page.locator('[data-purchase-return]').click();page.wait_for_url(f'**/ordini/{order_id}')
        page.locator('[data-purchase-return]').click();page.wait_for_url(listing)
        expect(page.locator('[name=q]')).to_have_value('Riviera')
        expect(page.locator('[data-purchase-return]')).to_be_hidden()
        # Native Back/Forward and reload keep the correct per-entry history.
        page.locator('.order-open').click();page.wait_for_url(f'**/ordini/{order_id}',wait_until='load')
        page.go_back();page.wait_for_url(listing,wait_until='load')
        page.go_forward();page.wait_for_url(f'**/ordini/{order_id}',wait_until='load');page.reload()
        expect(page.locator('[data-purchase-return]')).to_have_attribute('href',listing.replace(origin,''))
        # Main sections keep their last list filters without mixing detail histories.
        page.locator('[data-purchase-section=items]').click()
        page.get_by_label('Cerca articolo o codice',exact=True).fill('Gancio')
        page.get_by_role('button',name='Cerca',exact=True).click();page.wait_for_load_state('load');article_list=page.url
        page.locator('.warehouse-open').click()
        page.get_by_role('link',name='Modifica articolo',exact=False).click()
        page.locator('[name=descrizione]').fill('Modifica di prova')
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url(f'**/items/{item_id}/scheda')
        expect(page.locator('[data-purchase-return]')).to_have_attribute('href',article_list.replace(origin,''))
        page.get_by_role('link',name='Modifica articolo',exact=False).click()
        page.get_by_role('link',name='Annulla',exact=True).click();page.wait_for_url(f'**/items/{item_id}/scheda')
        expect(page.locator('[data-purchase-return]')).to_have_attribute('href',article_list.replace(origin,''))
        page.locator('[data-purchase-return]').click()
        page.locator('[data-purchase-section=orders]').click();page.wait_for_url(listing)
        page.locator('[data-purchase-section=items]').click();page.wait_for_url(article_list)
        for theme in ['light','dark']:
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            for path,label in [(listing,'orders'),(origin+f'/manager/fornitori/{supplier_id}','supplier'),(article_list,'articles')]:
                page.goto(path);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(artifacts/f'navigation-b-{label}-{theme}.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.goto(listing)
        page.get_by_role('button',name='Apri navigazione',exact=True).click()
        expect(page.locator('#workspace-sidebar')).to_have_attribute('aria-modal','true')
        page.screenshot(path=str(artifacts/'navigation-b-mobile-menu.png'),full_page=True)
        page.locator('[data-purchase-section=suppliers]').click()
        expect(page.locator('#workspace-sidebar')).to_have_attribute('aria-hidden','true')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(artifacts/'navigation-b-mobile-page.png'),full_page=True)
        # Storage unavailable: links and server-rendered parent navigation still work.
        fresh=browser.new_context(storage_state=context.storage_state(),viewport={'width':1440,'height':1000})
        fresh.add_init_script("Storage.prototype.getItem = () => {throw new Error('blocked')}; Storage.prototype.setItem = () => {throw new Error('blocked')};")
        fallback=fresh.new_page();fallback.goto(origin+f'/manager/ordini/{order_id}')
        expect(fallback.locator('[data-purchase-return]')).to_have_attribute('href','/manager/ordini')
        fallback.locator('[data-purchase-return]').click();fallback.wait_for_url('**/manager/ordini')
        fresh.close()
        assert not errors,errors
        print('NAVIGATION_B_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
