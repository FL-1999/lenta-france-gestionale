import os
import pytest
from playwright.sync_api import expect,sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import (Supplier,SupplierArticle,MagazzinoItem,MagazzinoCategoria,MagazzinoMacro,
                    MagazzinoRichiesta,MagazzinoRichiestaRiga,User,PurchaseOrder,Site)

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')

def test_article_suppliers_order_and_warehouse_layouts(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        vendors=[Supplier(name=f'Fornitore {n}',is_active=True) for n in range(4)]
        macro=MagazzinoMacro(name='Accessori sollevamento')
        cat=MagazzinoCategoria(nome='Ganci',slug='ganci',attiva=True,macro=macro)
        other=MagazzinoItem(nome='Altro materiale',attivo=True,quantita_disponibile=0,categoria=cat,soglia_minima=2)
        db.add_all([*vendors,other]);db.flush()
        site_id=db.query(Site).first().id
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        request=MagazzinoRichiesta(richiesto_da_user_id=manager.id,note='Prova grafica')
        db.add(request);db.flush()
        db.add(MagazzinoRichiestaRiga(richiesta_id=request.id,item_id=other.id,quantita_richiesta=1))
        db.commit();vendor_ids=[v.id for v in vendors];category_id=cat.id;macro_id=macro.id;other_id=other.id;request_id=request.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[];failures=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:failures.append(r.url) if r.status>=500 else None)
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/magazzino/nuovo')
        page.locator('input[name=nome]').fill('Gancio D13')
        page.locator('select[name=categoria_id]').select_option(str(category_id))
        page.locator('input[name=quantita_disponibile]').fill('4')
        for index,sid in enumerate(vendor_ids):
            page.locator('#add-article-supplier').click()
            row=page.locator('[data-supplier-row]').last
            row.locator('select').select_option(str(sid));row.locator('input').fill(f'VEND-{index}')
        page.locator('#add-article-supplier').click();page.locator('[data-supplier-row]').last.locator('[data-remove-supplier]').click()
        expect(page.locator('[data-supplier-row]')).to_have_count(4)
        page.screenshot(path=str(artifacts/'article-create-day.png'),full_page=True)
        page.locator('#theme-toggle').click()
        page.screenshot(path=str(artifacts/'article-create-night.png'),full_page=True)
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url('**/scheda')
        with Session(engine) as db:
            item=db.query(MagazzinoItem).filter_by(nome='Gancio D13').one();item_id=item.id;internal_code=item.codice
            assert db.query(SupplierArticle).filter_by(magazzino_item_id=item.id).count()==4
        page.locator('#fornitori tbody tr').filter(has_text='VEND-2').get_by_role('link',name='Ordina articolo').click()
        expect(page.locator('#supplier-id-select')).to_have_value(str(vendor_ids[2]))
        expect(page.locator('[name=magazzino_item_id]')).to_have_value(str(item_id))
        expect(page.locator('[data-codice]')).to_have_value('VEND-2')
        page.locator('[name=qty_ordered]').fill('3')
        page.get_by_role('button',name='Crea ordine',exact=True).click();page.wait_for_url('**/manager/ordini/*')
        with Session(engine) as db: assert db.query(PurchaseOrder).count()==1
        page.goto(origin+f'/manager/ordini/nuovo?supplier_id={vendor_ids[0]}')
        page.locator('[data-item-search]').fill(internal_code)
        page.locator('[name=magazzino_item_id]').select_option(str(item_id))
        expect(page.locator('[data-codice]')).to_have_value('VEND-0')
        page.locator('[data-item-search]').fill('Altro')
        page.locator('[name=magazzino_item_id]').select_option(str(other_id))
        expect(page.locator('[data-codice]')).to_have_value('')
        page.locator('[data-codice]').fill('VEND-0')
        expect(page.locator('[name=magazzino_item_id]')).to_have_value(str(item_id))
        expect(page.locator('[data-desc]')).to_have_value('Gancio D13')
        page.locator('#supplier-id-select').select_option(str(vendor_ids[1]))
        expect(page.locator('[data-codice]')).to_have_value('VEND-1')
        page.locator('[name=qty_ordered]').fill('2')
        page.locator('[data-codice]').fill('NEW-CODE')
        page.get_by_role('button',name='Crea ordine',exact=True).click();page.wait_for_url('**/manager/ordini/*')
        with Session(engine) as db:
            assert db.query(PurchaseOrder).count()==2
            assert db.query(SupplierArticle).filter_by(supplier_id=vendor_ids[1],codice='NEW-CODE').one().magazzino_item_id==item_id
        paths=['','/dashboard','/items','/archiviati','/sotto-soglia','/movimenti',f'/report-consumi?cantiere_id={site_id}','/macros','/categorie','/categorie/nuova','/macro/nuova',f'/macro/{macro_id}/modifica',f'/categorie/{category_id}/modifica',f'/categorie/{category_id}/sposta','/nuovo',f'/{item_id}/modifica',f'/items/{item_id}/duplica',f'/items/{item_id}/rettifica','/richieste',f'/richieste/{request_id}',f'/items/{item_id}/scheda']
        for size in [{'width':1440,'height':1000},{'width':390,'height':844}]:
            page.set_viewport_size(size)
            for path in paths:
                response=page.goto(origin+'/manager/magazzino'+path)
                assert response.status==200,(path,response.status)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),path
            page.screenshot(path=str(artifacts/f'warehouse-card-{size["width"]}.png'),full_page=True)
        page.goto(origin+'/manager/magazzino/nuovo')
        page.locator('#add-article-supplier').click()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(artifacts/'article-create-mobile-night.png'),full_page=True)
        page.locator('#theme-toggle').click()
        page.screenshot(path=str(artifacts/'article-create-mobile-day.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        for path,name in [('/categorie','categories'),('/movimenti','movements'),('/richieste','requests'),(f'/items/{item_id}/scheda','article-card')]:
            page.goto(origin+'/manager/magazzino'+path)
            page.screenshot(path=str(artifacts/f'warehouse-{name}-day.png'),full_page=True)
        assert not errors,errors
        assert not failures,failures
        print('ARTICLE_SUPPLIER_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
