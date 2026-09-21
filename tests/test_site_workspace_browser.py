import os
from pathlib import Path
from datetime import date
import pytest
import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site, User, Fiche, FicheTypeEnum
from test_operations_live import live_operations
from test_site_pours import setup

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_site_workspace_angle_pdf_and_status(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        site=db.get(Site,ids['site']);user=db.query(User).filter_by(email='smoke-manager@example.com').one()
        base=setup({'db':db,'site':site,'actor':[user],'manager':user})
    out=Path(os.getenv('WORKSPACE_SCREENSHOTS',str(artifacts)));out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda d:d.accept())
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+base)
        expect(page.locator('#sw-plan polygon')).to_have_count(2)
        for theme in ['dark','light']:
            page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            for width in [1440,390,320]:
                page.set_viewport_size({'width':width,'height':1100})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(theme,width)
            page.set_viewport_size({'width':1440,'height':1100})
            page.screenshot(path=str(out/f'site-workspace-{theme}.png'),full_page=True)
        page.locator('.sw-panel-list [data-panel="1"]').click()
        page.locator('[data-make-group=angle]').click()
        expect(page.locator('#sw-message')).to_have_text('Gruppo salvato.')
        page.locator('#sw-editor-body').get_by_role('link',name='Crea fiche').first.click()
        expect(page.locator('#larghezza_pannello')).to_have_value('8.0')
        expect(page.locator('[data-summary-number]')).to_have_text('P7 A/B')
        page.locator('#data_scavo').fill('2026-09-21');page.locator('#operatore').fill('Squadra prova')
        page.locator('#data_getto').fill('2026-09-21');page.locator('#metri_cubi_gettati').fill('42')
        page.locator('[data-strato-da]').first.fill('0');page.locator('[data-strato-a]').first.fill('10')
        page.locator('[name=strato_materiale]').first.select_option('sabbia')
        page.locator('form button[type=submit]').last.click();page.wait_for_url('**/manager/fiches/*')
        with Session(engine) as db:
            f=db.query(Fiche).one();fid=f.id;assert f.panel_name=='P7 A/B'
        page.goto(origin+f'/manager/fiches/{fid}')
        expect(page.locator('#technical-sheet-export')).to_contain_text('Fiche unica')
        for path,name,count in [(f'/manager/fiches/{fid}/pdf','angle.pdf',1),(base+'/fiches-pdf/paratie','angle-dossier.pdf',2)]:
            r=page.request.get(origin+path,timeout=60000);assert r.status==200,r.text()[:300]
            binary=r.body();(out/name).write_bytes(binary)
            doc=pdfium.PdfDocument(binary);assert len(doc)==count
            assert 'P7 A/B' in doc[count-1].get_textpage().get_text_range()
            doc[count-1].render(scale=1.4).to_pil().save(out/(name+'.png'));doc.close()
        page.goto(origin+base)
        assert page.locator('#sw-fiches').get_attribute('open') is None
        page.locator('#sw-fiches summary').click();expect(page.locator('#sw-fiches').get_by_role('link',name='Apri fiche',exact=True)).to_have_count(1)
        page.get_by_role('button',name='Segna come terminato',exact=True).click()
        expect(page.get_by_text('Stato del cantiere aggiornato. Dati e documenti conservati.')).to_be_visible()
        page.goto(origin+'/manager/cantieri?stato=terminati');expect(page.get_by_role('link',name='Cantiere Collaudo',exact=True)).to_be_visible()
        page.get_by_role('link',name='Cantiere Collaudo',exact=True).click();page.get_by_role('button',name='Riapri cantiere',exact=True).click()
        assert not errors,errors
        browser.close()



def test_joint_pour_manual_allocation_is_retained(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        site=db.get(Site,ids['site']);user=db.query(User).filter_by(email='smoke-manager@example.com').one()
        base=setup({'db':db,'site':site,'actor':[user],'manager':user},('P1','P2'))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page();page.on('dialog',lambda d:d.accept())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        for n in [1,2]:
            page.goto(origin+f'/manager/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello={n}')
            page.locator('#data_scavo').fill('2026-09-21');page.locator('#operatore').fill('Squadra prova')
            page.locator('#data_getto').fill('2026-09-21');page.locator('#metri_cubi_gettati').fill('8')
            page.locator('[data-strato-da]').first.fill('0');page.locator('[data-strato-a]').first.fill('10')
            page.locator('[name=strato_materiale]').first.select_option('sabbia')
            page.locator('form button[type=submit]').last.click();page.wait_for_url('**/manager/fiches/*')
        page.goto(origin+base);page.locator('#sw-multi').check()
        for n in [1,2]:page.locator(f'.sw-panel-list [data-panel="{n}"]').click()
        page.locator('[data-make-group=joint]').click()
        form=page.locator('#sw-cast-form');expect(form).to_be_visible()
        form.locator('[name=cast_date]').fill('2026-09-21');form.locator('[name=total_m3]').fill('40')
        expect(form.locator('[data-allocation]').nth(0)).to_have_value('25')
        expect(form.locator('[data-allocation]').nth(1)).to_have_value('15')
        form.locator('[name=manual]').check()
        form.locator('[data-allocation]').nth(0).fill('24');form.locator('[data-allocation]').nth(1).fill('16')
        with page.expect_navigation():form.locator('[type=submit]').click()
        page.locator('[data-group]').click();form=page.locator('#sw-cast-form')
        expect(form.locator('[name=manual]')).to_be_checked()
        expect(form.locator('[data-allocation]').nth(0)).to_have_value('24')
        expect(form.locator('[data-allocation]').nth(1)).to_have_value('16')
        with Session(engine) as db:assert sum(f.metri_cubi_gettati for f in db.query(Fiche))==40
        browser.close()
