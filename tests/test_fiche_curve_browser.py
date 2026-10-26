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
