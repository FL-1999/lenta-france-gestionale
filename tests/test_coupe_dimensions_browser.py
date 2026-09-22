import json
import os
import pytest
from playwright.sync_api import sync_playwright,expect
from sqlalchemy.orm import Session
from models import SiteCoupe,SiteCoupeAssignment,SitePlan,Site
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_separate_editors_and_width_changes_with_selected_panel(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        site=db.get(Site,ids['site']);site.numero_totale_paratie=2;site.numero_totale_pali=2
        paroi=SiteCoupe(site_id=site.id,nome='Coupe paroi',tipologia_scavo='paratia',spessore=.5,larghezza=99,quota_tn=20,quota_testa=20,profondita_teorica=10)
        pieu=SiteCoupe(site_id=site.id,nome='Coupe pieu',tipologia_scavo='palo',diametro=.8,profondita_teorica=15)
        db.add_all([paroi,pieu]);db.flush()
        panels=[]
        for n,width in [(1,6.4),(2,3.5)]:
            db.add(SiteCoupeAssignment(site_id=site.id,coupe_id=paroi.id,tipologia_scavo='paratia',numero_elemento=n))
            db.add(SiteCoupeAssignment(site_id=site.id,coupe_id=pieu.id,tipologia_scavo='palo',numero_elemento=n))
            panels.append({'key':str(n),'label':f'P{n}','element':n,'width_m':width,'points':[[0,n*20],[width*10,n*20],[width*10,n*20+5],[0,n*20+5]]})
        layout=json.dumps({'width':100,'height':100,'panels':panels})
        db.add(SitePlan(site_id=site.id,filename='test.pdf',pdf_data=b'test',preview_data=b'test',draft=layout,approved=layout))
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1500,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto')
        wall=page.locator('[data-coupe-card]').filter(has=page.locator('[name=coupe_nome][value="Coupe paroi"]'))
        pile=page.locator('[data-coupe-card]').filter(has=page.locator('[name=coupe_nome][value="Coupe pieu"]'))
        wall.locator('[data-focus-coupe]').click()
        expect(wall.locator('[name=coupe_spessore]')).to_be_visible()
        expect(wall.locator('[name=coupe_diametro]')).to_be_hidden()
        assert page.locator('[name=coupe_larghezza]').count()==0
        expect(pile).to_be_hidden()
        page.locator('[data-coupe-kind=palo]').click();pile.locator('[data-focus-coupe]').click()
        expect(pile.locator('[name=coupe_pali]')).to_be_visible()
        expect(pile.locator('[name=coupe_diametro]')).to_be_visible()
        expect(pile.locator('[name=coupe_spessore]')).to_be_hidden()
        expect(pile.locator('.coupe-picker')).to_be_hidden()
        page.locator('[data-add-coupe-card]').first.click()
        expect(page.locator('[data-coupe-card]:visible').last.locator('[name=coupe_tipologia_scavo]')).to_have_value('palo')
        page.goto(origin+f'/manager/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=1')
        width=page.locator('#larghezza_pannello');thickness=page.locator('#altezza_pannello')
        expect(width).to_have_value('6.4');assert width.evaluate('(e)=>e.readOnly')
        expect(thickness).to_have_value('0.5');assert thickness.evaluate('(e)=>e.readOnly')
        page.get_by_role('combobox',name='Pannello della pianta').select_option('2')
        expect(width).to_have_value('3.5');expect(thickness).to_have_value('0.5')
        assert not errors,errors
        browser.close()
