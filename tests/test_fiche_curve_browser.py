import os
from datetime import date

import pytest
import pypdfium2 as pdfium
from playwright.sync_api import expect,sync_playwright
from sqlalchemy.orm import Session
from models import Fiche,FicheTypeEnum,User
from test_operations_live import live_operations

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_curve_autofill_live_preview_save_and_a4(live_operations):
    origin,engine,ids,password,out=live_operations
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        f=Fiche(site_id=ids['site'],created_by_id=manager.id,date=date(2026,10,26),
                fiche_type=FicheTypeEnum.produzione,numero_pannello=5,panel_name='P5',description='Prova curva',
                tipologia_scavo='paratia',profondita_totale=10.7,larghezza_pannello=6.3,altezza_pannello=.42,
                quota_partenza=13.5,quota_tn=14.5,quota_testa_getto=13.5,quota_ngf_fondo=2.8,metri_cubi_gettati=38)
        db.add(f);db.commit();fid=f.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/fiches/{fid}'
        page.goto(url)
        form=page.locator('form[action$="/dati-pdf"]')
        form.locator('[name=courbe_beton_active]').check()
        expect(form.locator('[data-courbe-theoretical-volume]')).to_have_value('28.31')
        expect(form.locator('[data-courbe-theoretical-start]')).to_have_value('10.70')
        expect(form.locator('[data-courbe-theoretical-end]')).to_have_value('0')
        expect(form.locator('[data-courbe-status]')).to_contain_text('Curva teorica pronta')
        chart=form.locator('[data-courbe-chart]')
        expect(chart).to_be_visible()
        assert chart.evaluate("c=>Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data).some((v,i,a)=>i%4===0&&v>180&&a[i+1]<90&&a[i+2]<90)")
        form.locator('[name=larghezza_pannello]').fill('7')
        expect(form.locator('[data-courbe-theoretical-volume]')).to_have_value('31.46')
        form.locator('[data-courbe-theoretical-volume]').fill('32')
        form.locator('[name=larghezza_pannello]').fill('6.3')
        expect(form.locator('[data-courbe-theoretical-volume]')).to_have_value('32')
        form.locator('[data-courbe-reset]').click()
        expect(form.locator('[data-courbe-theoretical-volume]')).to_have_value('28.31')
        for index,(volume,depth) in enumerate([('0','10.7'),('20','5'),('38','0')]):
            if index:form.locator('[data-add-courbe-row=realisee]').click()
            row=form.locator('[data-courbe-table=realisee] .courbe-row').nth(index)
            row.locator('[data-courbe-volume]').fill(volume);row.locator('[data-courbe-hauteur]').fill(depth)
        chart.screenshot(path=str(out/'curve-editor.png'))
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            expect(chart).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.set_viewport_size({'width':1440,'height':1000})
        form.locator('button[type=submit]').click();page.wait_for_url(url)
        expect(page.locator('[data-report-model]')).to_have_attribute('data-report-model','B2')
        expect(page.locator('.b-curve-svg polyline')).to_have_count(2)
        with Session(engine) as db:
            f=db.get(Fiche,fid);assert f.courbe_beton_volume_total==28.31 and f.metri_cubi_gettati==38
        response=page.request.get(url+'/pdf',timeout=60000)
        assert response.status==200
        (out/'fiche-courbe-auto.pdf').write_bytes(response.body())
        doc=pdfium.PdfDocument(response.body());assert len(doc)==1
        assert doc[0].get_width()==pytest.approx(595.28,abs=1) and doc[0].get_height()==pytest.approx(841.89,abs=1)
        assert 'COURBE DE BÉTONNAGE' in doc[0].get_textpage().get_text_range()
        doc[0].render(scale=1.5).to_pil().save(out/'fiche-courbe-auto.png');doc.close()
        # Same automatic values in the full fiche editing form.
        page.goto(origin+f'/manager/fiches/{fid}/modifica')
        expect(page.locator('[data-courbe-theoretical-volume]')).to_have_value('28.31')
        expect(page.locator('[data-courbe-chart]')).to_be_visible()
        page.locator('[name=profondita_totale]').fill('11')
        expect(page.locator('[data-courbe-theoretical-volume]')).to_have_value('29.11')
        assert not errors,errors
        context.close();browser.close()


def test_reversed_volumes_are_reviewed_before_save_and_pdf_keeps_ngf(live_operations):
    import json
    origin,engine,ids,password,out=live_operations
    readings=[{'volume':v,'hauteur':d} for v,d in [(0,0),(2.5,2),(10,5),(17.5,7),(25,9),(32.5,11)]]
    raw=json.dumps(readings)
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        f=Fiche(site_id=ids['site'],created_by_id=manager.id,date=date(2026,10,26),
                fiche_type=FicheTypeEnum.produzione,numero_pannello=5,panel_name='P5',description='Prova abbinamento volumi',
                tipologia_scavo='paratia',profondita_totale=11,larghezza_pannello=6.3,altezza_pannello=.42,
                quota_partenza=13.8,quota_tn=14.5,quota_testa_getto=13.8,quota_ngf_fondo=2.8,metri_cubi_gettati=32.5,
                courbe_beton_active=True,courbe_beton_realisee=raw)
        db.add(f);db.commit();fid=f.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/fiches/{fid}'
        page.goto(url)
        form=page.locator('form[action$="/dati-pdf"]')
        table=form.locator('[data-courbe-table=realisee]')
        pairs=lambda:table.locator('.courbe-row').evaluate_all("rows=>rows.map(r=>[Number(r.querySelector('[data-courbe-volume]').value),Number(r.querySelector('[data-courbe-hauteur]').value)])")
        expect(table.locator('[data-courbe-direction-message]')).to_be_visible()
        assert pairs()==[[32.5,11],[25,9],[17.5,7],[10,5],[2.5,2],[0,0]]
        # Sorting must never change volume/depth associations.
        table.locator('[data-courbe-order]').click()
        assert sorted(pairs())==[[0,0],[2.5,2],[10,5],[17.5,7],[25,9],[32.5,11]]
        table.locator('[data-courbe-review-volumes]').click()
        proposal=table.locator('[data-courbe-volume-proposal]')
        expect(proposal).to_be_visible()
        with Session(engine) as db:assert db.get(Fiche,fid).courbe_beton_realisee==raw
        for width in [390,320]:
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.set_viewport_size({'width':390,'height':844})
        proposal.screenshot(path=str(out/'curve-volume-review-mobile.png'))
        table.locator('[data-courbe-apply-volumes]').click()
        corrected=[[32.5,0],[25,2],[17.5,5],[10,7],[2.5,9],[0,11]]
        assert pairs()==corrected
        expect(table.locator('[data-courbe-direction-message]')).not_to_be_visible()
        with Session(engine) as db:assert db.get(Fiche,fid).courbe_beton_realisee==raw
        page.set_viewport_size({'width':1440,'height':1000})
        form.locator('[data-courbe-chart]').screenshot(path=str(out/'curve-corrected.png'))
        form.locator('button[type=submit]').click();page.wait_for_url(url)
        assert pairs()==corrected
        with Session(engine) as db:
            f=db.get(Fiche,fid)
            assert json.loads(f.courbe_beton_realisee)==[{'volume':v,'hauteur':d} for v,d in reversed(corrected)]
            assert f.metri_cubi_gettati==32.5
        # Both the real and theoretical lines rise from bottom left to top right.
        lines=page.locator('.b-curve-svg polyline').evaluate_all("ls=>ls.map(l=>l.getAttribute('points').split(' ').map(p=>p.split(',').map(Number)))")
        assert len(lines)==2
        for line in lines:assert line[0][0]<line[-1][0] and line[0][1]>line[-1][1]
        response=page.request.get(url+'/pdf',timeout=60000);assert response.status==200
        (out/'fiche-curva-profondita.pdf').write_bytes(response.body())
        doc=pdfium.PdfDocument(response.body());assert len(doc)==1
        assert doc[0].get_width()==pytest.approx(595.28,abs=1) and doc[0].get_height()==pytest.approx(841.89,abs=1)
        text=doc[0].get_textpage().get_text_range()
        assert 'COURBE DE BÉTONNAGE' in text and 'NGF' in text
        doc[0].render(scale=1.5).to_pil().save(out/'fiche-curva-profondita.png');doc.close()
        page.goto(url+'/modifica')
        edit=page.locator('[data-courbe-table=realisee]')
        expect(edit.locator('[data-courbe-volume]').first).to_have_value('32.5')
        expect(edit.locator('[data-courbe-hauteur]').first).to_have_value('0.0')
        assert not errors,errors
        context.close();browser.close()
