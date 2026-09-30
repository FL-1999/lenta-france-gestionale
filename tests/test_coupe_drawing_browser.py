import os
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import SiteCoupe
from test_operations_live import live_operations
from test_coupe_drawing import section_pdf

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_read_review_correct_and_save_coupe(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.context.add_cookies([{'name':'lang','value':'fr','url':origin}])
        config=origin+f'/manager/cantieri/{ids["site"]}/configurazione-progetto';page.goto(config)
        card=page.locator('[data-coupe-card]').first
        card.locator('[data-read-coupe-pdf]').click()
        page.locator('[data-reader-file]').set_input_files({'name':'Coupe revue.pdf','mimeType':'application/pdf','buffer':section_pdf(two=True)})
        page.locator('[data-reader-load]').click()
        expect(page.locator('[data-reader-warnings]')).to_contain_text('Plusieurs coupes')
        expect(page.locator('[data-reader-apply]')).to_be_disabled()
        image=page.locator('.reader-preview');image.scroll_into_view_if_needed()
        bounds=image.bounding_box()
        page.mouse.move(bounds['x']+1,bounds['y']+1);page.mouse.down()
        page.mouse.move(bounds['x']+bounds['width']*.5,bounds['y']+bounds['height']-1,steps=8);page.mouse.up()
        page.locator('[data-reader-crop]').click()
        expect(page.locator('[data-reader-apply]')).to_be_enabled()
        expect(page.locator('[data-reader-values]')).to_contain_text('11.7')
        page.screenshot(path=str(artifacts/'coupe-pdf-reader.png'),full_page=True)
        page.locator('[data-reader-apply]').click()
        expect(card.locator('[name=coupe_quota_tn]')).to_have_value('14.5')
        expect(card.locator('[name=coupe_profondita_teorica]')).to_have_value('11.7')
        expect(card.locator('[data-strut-row]')).to_have_count(1)
        expect(card.locator('[data-strut-row] input')).to_have_value('12')
        expect(card.locator('[data-treatment-top]')).to_have_value('4.8')
        card.locator('[data-add-strut]').click()
        card.locator('[data-strut-row] input').last.fill('8.5')
        card.locator('[data-coupe-reviewed]').check()
        card.locator('[name=coupe_note]').fill('Note conservée')
        card.locator('[name=coupe_profondita_teorica]').fill('10.7')
        with page.expect_response(lambda r:r.request.method=='POST' and 'configurazione-progetto' in r.url) as response:
            page.locator('.project-sticky-actions button[type=submit]').click()
        assert response.value.status==400
        expect(page.locator('#coupe-errors')).to_be_visible()
        card=page.locator('[data-coupe-card]').first
        expect(card.locator('[name=coupe_note]')).to_have_value('Note conservée')
        expect(card.locator('[data-strut-row]')).to_have_count(2)
        card.locator('[name=coupe_profondita_teorica]').fill('11.7')
        with page.expect_response(lambda r:r.request.method=='POST' and 'configurazione-progetto' in r.url) as response:
            page.locator('.project-sticky-actions button[type=submit]').click()
        assert response.value.status==303
        page.wait_for_url('**/configurazione-progetto?saved=1')
        with Session(engine) as db:
            row=db.query(SiteCoupe).filter_by(site_id=ids['site'],nome='Coupe 2').one()
            assert row.drawing_info['struts']==[12,8.5]
            assert row.drawing_info['treatment']['bottom']==3.3
        page.goto(origin+f'/manager/cantieri/{ids["site"]}')
        expect(page.locator('.coupe-site-info')).to_contain_text('Niveau −2')
        expect(page.locator('.coupe-site-info')).to_contain_text('+8.50')
        assert not errors,errors
        browser.close()
