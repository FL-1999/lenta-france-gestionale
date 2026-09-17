import os
import pytest
from playwright.sync_api import expect,sync_playwright
from sqlalchemy.orm import Session
from test_operations_live import live_operations
from models import MagazzinoItem,MagazzinoCategoria,MagazzinoMacro,Supplier,SupplierArticle

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_create_classification_from_empty_catalog(live_operations):
    from models import PurchaseOrder, MagazzinoMovimento
    origin,engine,ids,password,artifacts=live_operations
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/magazzino')
        page.get_by_role('link',name='Nuova categoria',exact=True).click()
        expect(page.get_by_text('Crea prima una macro',exact=False)).to_be_visible()
        page.get_by_role('link',name='Nuova macro',exact=True).click()
        page.get_by_label('Nome macro',exact=False).fill('Accessori sollevamento')
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url('**/categorie')
        page.locator('.macro-card').filter(has_text='Accessori sollevamento').get_by_role('link',name='Nuova categoria',exact=True).click()
        expect(page.locator('#macro_id option:checked')).to_have_text('Accessori sollevamento')
        page.get_by_label('Nome',exact=False).fill('Catene')
        page.get_by_role('button',name='Salva',exact=True).click();page.wait_for_url('**/categorie')
        expect(page.locator('.categoria-name')).to_contain_text('Catene')
        page.goto(origin+'/manager/magazzino')
        page.locator('.warehouse-macro').filter(has_text='Accessori sollevamento').click()
        expect(page.locator('.warehouse-family')).to_contain_text('Catene')
        page.get_by_role('link',name='Nuova categoria',exact=True).click()
        expect(page.locator('#macro_id option:checked')).to_have_text('Accessori sollevamento')
        for theme in ['light','dark']:
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':900})
                for path,label in [('/manager/magazzino','catalog'),('/manager/magazzino/categorie','categories'),('/manager/magazzino/categorie/nuova','category-form'),('/manager/magazzino/macro/nuova','macro-form')]:
                    page.goto(origin+path)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(path,width)
                    page.screenshot(path=str(artifacts/f'catalog-create-{label}-{theme}-{width}.png'),full_page=True)
        assert not errors,errors
        context.close();browser.close()
    with Session(engine) as db:
        assert db.query(MagazzinoMacro).count()==db.query(MagazzinoCategoria).count()==1
        assert db.query(PurchaseOrder).count()==db.query(MagazzinoItem).count()==db.query(MagazzinoMovimento).count()==0


def test_a1_catalog_location_themes_and_mobile(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        macro=MagazzinoMacro(name='Materiali di cantiere')
        cat=MagazzinoCategoria(nome='Ferramenta',slug='ferramenta',attiva=True,macro=macro)
        item=MagazzinoItem(nome='Bullone M12',categoria=cat,quantita_disponibile=240,attivo=True)
        db.add(item);db.flush()
        for n in range(4):
            supplier=Supplier(name=f'Fornitore prova {n}',is_active=True);db.add(supplier);db.flush()
            db.add(SupplierArticle(supplier_id=supplier.id,codice=f'BOLT-{n}',magazzino_item_id=item.id))
        for name,qty in [('Rondella M12',180),('Dado M12',0)]:db.add(MagazzinoItem(nome=name,categoria=cat,attivo=True,quantita_disponibile=qty))
        db.commit();item_id=item.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page=context.new_page();errors=[];failures=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:failures.append(r.url) if r.status>=500 else None)
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');expect(page.locator('.workspace-wordmark')).to_be_visible()
        page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/magazzino')
        expect(page.locator('.warehouse-row')).to_have_count(0)
        page.locator('.warehouse-family').filter(has_text='Materiali di cantiere').click()
        expect(page.locator('.warehouse-row')).to_have_count(0)
        page.locator('.warehouse-family').filter(has_text='Ferramenta').click()
        expect(page.locator('.warehouse-breadcrumbs')).to_contain_text('Materiali di cantiere')
        expect(page.locator('.warehouse-breadcrumbs')).to_contain_text('Ferramenta')
        expect(page.locator('.warehouse-row')).to_have_count(3)
        expect(page.locator('.warehouse-row').filter(has_text='Bullone M12')).to_contain_text('4 fornitori')
        expect(page.locator('.workspace-wordmark')).to_be_visible()
        page.screenshot(path=str(artifacts/'a1-day.png'),full_page=True)
        page.locator('#theme-toggle').click();expect(page.locator('html')).to_have_attribute('data-theme','dark')
        page.screenshot(path=str(artifacts/'a1-night.png'),full_page=True)
        page.get_by_role('link',name='Apri scheda: Bullone M12',exact=True).click()
        page.get_by_text('Aggiungi posizione',exact=True).click()
        page.locator('input[name=scaffale]').fill('B-12')
        page.get_by_role('button',name='Salva posizione').click()
        expect(page.locator('#posizione')).to_contain_text('B-12')
        expect(page.locator('#posizione')).to_contain_text('Posizione aggiornata')
        page.get_by_text('Modifica posizione',exact=True).click()
        page.locator('input[name=zona]').fill('Deposito principale')
        page.locator('input[name=ripiano]').fill('3')
        page.get_by_role('button',name='Salva posizione').click()
        expect(page.locator('#posizione')).to_contain_text('Deposito principale')
        page.screenshot(path=str(artifacts/'a1-article.png'),full_page=True)
        for theme in ['dark','light']:
            page.set_viewport_size({'width':390,'height':844})
            if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme-toggle').click()
            for path in ['/manager/magazzino',f'/manager/magazzino/items/{item_id}/scheda']:
                page.goto(origin+path)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),path
            page.screenshot(path=str(artifacts/f'a1-mobile-{theme}.png'),full_page=True)
        page.get_by_text('Modifica posizione',exact=True).click()
        page.get_by_role('button',name='Rimuovi posizione').click()
        expect(page.locator('#posizione')).to_contain_text('Non assegnata')
        assert not errors,errors
        assert not failures,failures
        print('WAREHOUSE_A1_SCREENSHOTS='+str(artifacts))
        context.close();browser.close()
