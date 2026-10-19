import json
import os
from pathlib import Path

import pytest
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site, SitePlan, SiteCoupe, Fiche, FicheTypeEnum
from datetime import date
from services.site_plan_import import import_pdf
from services.site_plan_project import confirm_project_panels
from test_operations_live import live_operations
from test_site_plans import vector_pdf

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1', reason='Browser checks opt-in')


def test_visual_coupe_selection_fiche_creation_and_real_pdf_routes(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    layout,preview=import_pdf(vector_pdf())
    layout['panels'][0].update(element=21,label='P5',width_m=5.2,reviewed=True)
    layout['panels'].append({**layout['panels'][0],'element':22,'key':'other','label':'P8B',
                             'points':[[50,210],[190,210],[190,235],[50,235]]})
    with Session(engine) as db:
        site=db.get(Site,ids['site']);confirm_project_panels(db,site,layout)
        db.add(SitePlan(site_id=site.id,filename='Prova.pdf',pdf_data=vector_pdf(),preview_data=preview,
                       draft=json.dumps(layout),approved=json.dumps(layout),approved_revision=1))
        db.commit()
    out=Path(os.getenv('WORKSPACE_SCREENSHOTS',str(artifacts)));out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        config=origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto'
        page.goto(config)
        first=page.locator('[data-coupe-card]').first
        expect(first.locator('.coupe-panel-grid button')).to_have_count(22)
        first.locator('.coupe-panel-grid').get_by_role('button',name='P5',exact=True).click()
        values={'coupe_nome':'Coupe 1','coupe_quota_reference_label':'NGM','coupe_quota_tn':'10.5',
                'coupe_quota_testa':'10.5','coupe_quota_fondo_teorica':'-1.5',
                'coupe_base_paroi_mecanique':'-1.38','coupe_quota_testa_getto_prevista':'10.5',
                'coupe_spessore':'.42'}
        for key,value in values.items():first.locator(f'[name="{key}"]').fill(value)
        page.locator('[data-add-coupe-card]').first.click()
        second=page.locator('[data-coupe-card]').nth(1)
        expect(second.locator('.coupe-panel-grid').get_by_role('button',name='P5')).to_be_disabled()
        second.locator('[name=coupe_nome]').fill('Coupe 2')
        second.locator('.coupe-panel-grid').get_by_role('button',name='P8B',exact=True).click()
        page.get_by_role('button',name='Salva configurazione progetto').click()
        expect(page.get_by_role('status')).to_contain_text('salvata')
        with Session(engine) as db:
            assert db.query(SiteCoupe).count()==2
        first=page.locator('[data-coupe-card]').first
        first.locator('.coupe-editor > summary').click()
        expect(first.locator('[name=coupe_profondita_teorica]')).to_have_value('12.0')
        for theme in ['dark','light']:
            page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            page.add_style_tag(content='*,*::before,*::after{transition:none!important;animation:none!important}')
            for width in [1440,390]:
                page.set_viewport_size({'width':width,'height':1050})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'coupe-{theme}-{width}.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1050})
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        page.get_by_role('link',name='Crea fiche',exact=True).click()
        expect(page.locator('#numero_pannello')).to_have_value('21')
        expect(page.locator('#numero_pannello')).to_be_hidden()
        expect(page.get_by_role('combobox',name='Pannello / palo')).to_have_value('21')
        expect(page.locator('#macchinario_id')).to_have_value('')
        expect(page.locator('#larghezza_pannello')).to_have_value('5.2')
        expect(page.locator('#quota_ngf_fondo')).to_have_value('-1.50')
        expect(page.locator('[data-summary-number]')).to_have_text('P5')
        # Changing coupe used to overwrite P5 with the internal 21.
        coupe_value=page.locator('#coupe_id').input_value()
        page.locator('#coupe_id').select_option('')
        expect(page.locator('[data-summary-number]')).to_have_text('P5')
        page.locator('#coupe_id').select_option(coupe_value)
        page.locator('#cantiere_id').select_option(str(ids['other']))
        expect(page.locator('#numero_pannello')).to_be_visible()
        expect(page.locator('#numero_pannello')).to_have_value('')
        page.locator('#cantiere_id').select_option(str(ids['site']))
        expect(page.locator('#fiche_panel')).to_have_value('')
        page.locator('#fiche_panel').select_option('5')
        expect(page.locator('[data-summary-number]')).to_have_text('5')
        expect(page.locator('#fiche-panel-help')).to_contain_text('non presente nella piantina')
        assert not page.locator('#larghezza_pannello').evaluate('(e)=>e.readOnly')
        page.locator('#fiche_panel').select_option('21')
        expect(page.locator('[data-summary-number]')).to_have_text('P5')
        assert page.locator('[data-fiche-form]').evaluate("e=>new FormData(e).getAll('numero_pannello')")==['21']
        for width in [1440,390,320]:
            page.set_viewport_size({'width':width,'height':1000})
            expect(page.locator('#numero_pannello')).to_be_hidden()
            expect(page.get_by_role('combobox',name='Pannello / palo')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            page.screenshot(path=str(out/f'fiche-panel-{width}.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1050})
        page.locator('#data_scavo').fill('2026-09-17')
        page.locator('#operatore').fill('Squadra di prova')
        page.locator('#data_getto').fill('2026-09-17');page.locator('#metri_cubi_gettati').fill('27.5')
        page.locator('[data-strato-da]').first.fill('0');page.locator('[data-strato-a]').first.fill('12')
        page.locator('[name="strato_materiale"]').first.select_option('sabbia')
        page.locator('form button[type=submit]').last.click()
        page.wait_for_url('**/manager/fiches/*')
        with Session(engine) as db:
            fiche=db.query(Fiche).one();fid=fiche.id
            assert fiche.numero_pannello==21 and fiche.panel_name=='P5'
        page.goto(origin+f'/manager/fiches/{fid}/modifica')
        expect(page.locator('#fiche_panel')).to_have_value('21')
        expect(page.locator('#numero_pannello')).to_be_hidden()
        expect(page.locator('[data-summary-number]')).to_have_text('P5')
        page.goto(origin+f'/manager/fiches/{fid}')
        expect(page.locator('#technical-sheet-export')).to_contain_text('P5')
        expect(page.locator('#technical-sheet-export')).to_contain_text('Coupe 1')
        page.locator('.technical-coupe-card').screenshot(path=str(out/'technical-sheet.png'))
        with Session(engine) as db:
            source=db.get(Fiche,fid)
            db.add(Fiche(site_id=source.site_id,created_by_id=source.created_by_id,date=date(2026,9,17),
                         numero_pannello=1,panel_name='Palo A',tipologia_scavo='palo',fiche_type=FicheTypeEnum.produzione,
                         description='Prova dossier misto',profondita_totale=10,diametro_palo=.8,
                         quota_tn=10.5,quota_partenza=10.5,quota_ngf_fondo=.5))
            db.commit()
        for path,name,expected_pages in [(f'/manager/fiches/{fid}/pdf','fiche-prova.pdf',1),
                                         (f'/manager/cantieri/{ids["site"]}/fiches-pdf/tutte','dossier-prova.pdf',3)]:
            response=page.request.get(origin+path,timeout=60000)
            assert response.status==200,response.text()[:500]
            binary=response.body();(out/name).write_bytes(binary)
            doc=pdfium.PdfDocument(binary)
            assert len(doc)==expected_pages
            sheet=doc[0] if expected_pages==1 else next(doc[i] for i in range(1,len(doc)) if 'P5' in doc[i].get_textpage().get_text_range())
            text=sheet.get_textpage().get_text_range()
            assert 'P5' in text and 'NGM' in text and 'Coupe 1' in text
            if expected_pages==1:assert '_P5_' in response.headers['content-disposition']
            sheet.render(scale=1.6).to_pil().save(out/(name+'.png'))
            if expected_pages==3:
                assert any('Palo A' in doc[i].get_textpage().get_text_range() for i in range(1,len(doc)))
                doc[0].render(scale=1.6).to_pil().save(out/'dossier-cover.png')
            doc.close()
        # Native form submission has one authoritative selected value even without JS.
        plain_context=browser.new_context(java_script_enabled=False,storage_state=page.context.storage_state())
        plain=plain_context.new_page()
        plain.goto(origin+f'/manager/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=22')
        expect(plain.locator('#numero_pannello')).to_be_hidden()
        plain.locator('#fiche_panel').select_option('21')
        assert plain.locator('[data-fiche-form]').evaluate("e=>new FormData(e).getAll('numero_pannello')")==['21']
        plain_context.close()
        # The same selection and label are available to the crew leader.
        capo=browser.new_page(viewport={'width':390,'height':844})
        capo.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        capo.goto(origin+'/login');capo.locator('#email').fill('smoke-capo@example.com');capo.locator('#password').fill(password)
        capo.locator('#login-form button[type=submit]').click();capo.wait_for_url('**/capo/dashboard')
        capo.goto(origin+'/capo/fiches')
        expect(capo.locator('.mobile-directory')).to_contain_text('P5')
        capo.goto(origin+f'/capo/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=22')
        expect(capo.locator('[data-summary-number]')).to_have_text('P8B')
        expect(capo.locator('#numero_pannello')).to_be_hidden()
        picker=capo.get_by_role('combobox',name='Pannello / palo')
        picker.select_option('21')
        expect(capo.locator('[data-summary-number]')).to_have_text('P5')
        picker.select_option('')
        expect(capo.locator('#numero_pannello')).to_have_value('')
        assert not picker.evaluate('(e)=>e.checkValidity()')
        picker.select_option('22')
        capo.locator('#tipologia_scavo').select_option('palo')
        expect(picker).to_be_hidden()
        expect(capo.locator('#numero_pannello')).to_be_visible()
        expect(capo.locator('#numero_pannello')).to_have_value('')
        capo.locator('#numero_pannello').fill('5')
        expect(capo.locator('[data-summary-number]')).to_have_text('5')
        capo.locator('#tipologia_scavo').select_option('paratia')
        expect(picker).to_have_value('')
        assert not errors,errors
        browser.close()

