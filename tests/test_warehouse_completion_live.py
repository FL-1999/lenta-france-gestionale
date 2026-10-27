import os
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import (Supplier, SupplierArticle, WarehouseSupplierPending, MagazzinoItem,
                    MagazzinoMacro, MagazzinoCategoria)

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_completion_navigation_create_fill_and_phone(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        vendor=Supplier(name='Fornitore di prova',is_active=True)
        cat=MagazzinoCategoria(nome='Bulloneria',slug='bulloneria-test',attiva=True,
                              macro=MagazzinoMacro(name='Ferramenta'))
        item=MagazzinoItem(nome='Guanti senza fornitore',categoria=cat,attivo=True,quantita_disponibile=12)
        free=MagazzinoItem(nome='Raccordo da classificare',attivo=True)
        db.add_all([vendor,item,free]);db.commit();sid=vendor.id;cid=cat.id;mid=cat.macro_id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password);page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/magazzino')
        expect(page.locator('.warehouse-completion-entry')).to_contain_text('Da completare')
        expect(page.locator('.warehouse-rows')).to_have_count(0)
        page.locator('.warehouse-macro').filter(has_text='Ferramenta').click()
        page.locator('.warehouse-family').filter(has_text='Bulloneria').click()
        page.get_by_role('link',name='Nuovo articolo',exact=True).click()
        expect(page.locator('[name=categoria_id]')).to_have_value(str(cid))
        page.locator('[name=nome]').fill('Bullone senza codice')
        page.locator('[name=quantita_disponibile]').fill('20')
        page.locator('#add-article-supplier').click()
        page.locator('[name=supplier_ids]').select_option(str(sid))
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url('**/scheda')
        expect(page.locator('.warehouse-pending-supplier')).to_contain_text('Fornitore di prova')
        with Session(engine) as db:
            saved=db.query(MagazzinoItem).filter_by(nome='Bullone senza codice').one();item_id=saved.id
            assert saved.categoria_id==cid and saved.quantita_disponibile==20
            assert db.query(SupplierArticle).count()==0 and db.query(WarehouseSupplierPending).count()==1
        page.goto(origin+'/manager/magazzino/da-completare?kind=code')
        expect(page.locator('.warehouse-completion-row')).to_have_count(1)
        page.locator('.warehouse-completion-editor summary').click()
        page.locator('[name=code]').fill('SKU-VERO')
        page.get_by_role('button',name='Salva codice',exact=True).click()
        expect(page.locator('.warehouse-completion-row')).to_have_count(0)
        expect(page.locator('[role=status]')).to_contain_text('promemoria è aggiornato')
        with Session(engine) as db:
            saved=db.get(MagazzinoItem,item_id)
            assert saved.categoria_id==cid and saved.quantita_disponibile==20
            assert db.query(WarehouseSupplierPending).count()==0
            assert db.query(SupplierArticle).one().codice=='SKU-VERO'
        page.goto(origin+'/manager/magazzino/da-completare?kind=supplier')
        row=page.locator('.warehouse-completion-row').filter(has_text='Guanti senza fornitore')
        row.locator('summary').click();row.locator('[name=supplier_id]').select_option(str(sid))
        row.get_by_role('button',name='Salva fornitore',exact=True).click()
        expect(page.locator('.warehouse-completion-row').filter(has_text='Guanti senza fornitore')).to_have_count(0)
        page.goto(origin+'/manager/magazzino/da-completare?kind=code')
        expect(page.locator('.warehouse-completion-row')).to_contain_text('Guanti senza fornitore')
        for lang in ['it','fr']:
            context.add_cookies([{'name':'lang','value':lang,'url':origin}])
            for width in [1440,390,320]:
                page.set_viewport_size({'width':width,'height':844 if width<500 else 1000})
                for theme in ['day','night']:
                    if theme=='night': page.locator('#theme-toggle').click()
                    for path in ['/manager/magazzino','/manager/magazzino/da-completare',
                                 '/manager/magazzino/da-completare?kind=supplier',
                                 f'/manager/magazzino/items/{item_id}/scheda']:
                        page.goto(origin+path)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),(width,lang,path)
                        if path == '/manager/magazzino':
                            page.screenshot(path=str(artifacts/f'warehouse-entry-{lang}-{width}-{theme}.png'),full_page=True)
                        if path.endswith('/da-completare'):
                            page.screenshot(path=str(artifacts/f'completion-{lang}-{width}-{theme}.png'),full_page=True)
                    if theme=='night': page.locator('#theme-toggle').click()
        assert not errors,errors
        print('WAREHOUSE_COMPLETION_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
