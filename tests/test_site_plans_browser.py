import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Site
from test_operations_live import live_operations
from test_site_plans import vector_pdf

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser checks opt-in')


def test_import_edit_confirm_and_reload(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        db.get(Site,ids['site']).numero_totale_paratie=30;db.commit()
    source=os.getenv('SITE_PLAN_SAMPLE_PDF')
    sample=Path(source).read_bytes() if source else vector_pdf()
    output=Path(os.getenv('WORKSPACE_SCREENSHOTS',str(artifacts)));output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1600,'height':1100})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        page.locator('input[name=file]').set_input_files({'name':'Papon.pdf','mimeType':'application/pdf','buffer':sample})
        page.locator('[data-upload] button[type=submit]').click()
        expect(page.locator('[data-workspace]')).to_be_visible(timeout=20000)
        expect(page.locator('[data-save]')).to_be_enabled()
        page.evaluate("document.documentElement.dataset.theme='dark'")
        if source:expect(page.locator('[data-counter]')).to_have_text('29 pannelli')
        page.locator('#site-plan-app').screenshot(path=str(output/'site-plan-import.png'))
        picker=page.locator('[data-select]');options=picker.locator('option').evaluate_all('(els)=>els.map(e=>({value:e.value,text:e.textContent}))')
        p7=next(v for v in options if v['text'].startswith('P7a'))
        picker.select_option(p7['value'])
        expect(page.locator('[data-editor] [name=width_m]')).to_have_value('2.9')
        page.locator('[data-zoom]').click()
        shape=page.locator('[data-original-shapes] polygon.selected')
        bounds=shape.bounding_box()
        before=float(page.locator('[name=cx]').input_value())
        page.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2)
        page.mouse.down();page.mouse.move(bounds['x']+bounds['width']/2+8,bounds['y']+bounds['height']/2+4,steps=4);page.mouse.up()
        assert float(page.locator('[name=cx]').input_value())>before
        page.locator('[data-fit]').click()
        page.locator('[data-editor] [name=label]').fill('P7A prova')
        page.locator('[data-editor] [name=width_m]').fill('3.2')
        page.locator('[data-editor] [name=element]').select_option('1')
        page.locator('[data-scale]').click()
        if page.locator('[name=extent_confirmed]').is_visible(): page.locator('[name=extent_confirmed]').check()
        page.locator('[data-editor] [name=reviewed]').check()
        page.locator('[data-save]').click();expect(page.locator('[data-message]')).to_contain_text('Bozza salvata')
        page.reload();expect(page.locator('[data-workspace]')).to_be_visible()
        picker.select_option(p7['value']);expect(page.locator('[data-editor] [name=label]')).to_have_value('P7A prova')
        expect(page.locator('[data-editor] [name=width_m]')).to_have_value('3.2')
        for option in options:
            picker.select_option(option['value'])
            if page.locator('[name=extent_confirmed]').is_visible(): page.locator('[name=extent_confirmed]').check()
        page.locator('[data-review-all]').click();page.locator('[data-approve]').click()
        expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        expect(page.locator('[data-editor]')).to_be_hidden()
        page.reload();expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        page.locator('[data-original-toggle]').click()
        for theme in ['dark','light']:
            page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
            for width in [1440,1024,390,320]:
                page.set_viewport_size({'width':width,'height':1200})
                assert page.locator('#site-plan-app').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),(theme,width)
                assert page.locator('[data-original-svg] .sp-panel:not(.selected)').first.evaluate('(e)=>getComputedStyle(e).stroke') in ['rgba(0, 0, 0, 0)','transparent'] if source else True
            page.set_viewport_size({'width':1600,'height':1200})
            page.locator('#site-plan-app').screenshot(path=str(output/f'site-plan-{theme}.png'))
        page.locator('[data-edit]').click();expect(page.locator('[data-save-section]')).to_be_visible()
        page.locator('[data-select]').select_option(p7['value']);page.locator('[data-remove]').click()
        page.locator('[data-confirm-action]').click()
        page.locator('[data-save]').click();expect(page.locator('[data-message]')).to_contain_text('Bozza salvata')
        page.reload();expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        assert page.locator('[data-select] option').count()==len(options)
        assert not errors,errors
        browser.close()


def test_replace_remove_and_restore_pdf_and_internal_panel_confirmation(live_operations):
    from models import User, RoleEnum, Role, UserRole
    origin,engine,ids,password,artifacts=live_operations
    with Session(engine) as db:
        user=db.query(User).filter_by(email='smoke-manager@example.com').one()
        user.role=RoleEnum.admin
        admin_role=db.query(Role).filter_by(name=RoleEnum.admin).first()
        if admin_role is None:
            admin_role=Role(name=RoleEnum.admin);db.add(admin_role);db.flush()
        user.user_roles=[UserRole(role=admin_role)]
        db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];dialogs=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('dialog',lambda dialog:(dialogs.append(dialog.type),dialog.dismiss()))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        def upload(name,content):
            page.locator('input[name=file]').set_input_files({'name':name,'mimeType':'application/pdf','buffer':content})
            page.locator('[data-upload] button[type=submit]').click()
        upload('first.pdf',vector_pdf());expect(page.locator('[data-workspace]')).to_be_visible()
        page.locator('[data-remove]').click()
        expect(page.locator('[data-confirm-dialog]')).to_be_visible()
        page.locator('[data-confirm-dialog] [value=cancel]').click()
        expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        page.locator('[data-remove]').click();page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-counter]')).to_have_text('0 pannelli')
        page.locator('[data-undo-removal]').click();expect(page.locator('[data-counter]')).to_have_text('1 pannello')
        page.locator('[data-save]').click();expect(page.locator('[data-message]')).to_contain_text('Bozza salvata')
        page.locator('[data-replace]').click();upload('invalid.pdf',b'not pdf');page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-message]')).to_have_attribute('data-error','true')
        expect(page.locator('[data-version] option')).to_contain_text('first.pdf')
        upload('second.pdf',vector_pdf());page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-version] option')).to_contain_text('second.pdf')
        expect(page.locator('[data-version] option')).to_have_count(1)
        page.locator('[data-remove-draft]').click()
        page.set_viewport_size({'width':390,'height':900})
        expect(page.locator('[data-confirm-dialog]')).to_be_visible()
        assert page.locator('[data-confirm-dialog]').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        assert page.locator('#sp-confirm-text').evaluate('(e)=>getComputedStyle(e).color')=='rgb(22, 43, 65)'
        page.screenshot(path=str(artifacts/'draft-removal-mobile.png'))
        page.locator('[data-confirm-action]').click()
        expect(page.locator('[data-workspace]')).to_be_hidden();expect(page.locator('[data-upload]')).to_be_visible()
        page.locator('[data-removed] summary').click()
        page.locator('.sp-removed-row').filter(has_text='first.pdf').get_by_role('button').click()
        expect(page.locator('[data-version] option')).to_contain_text('first.pdf')
        page.reload();expect(page.locator('[data-version] option')).to_contain_text('first.pdf')
        page.goto(origin+'/set-language/fr');page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        expect(page.locator('[data-replace]')).to_have_text('Remplacer le PDF')
        page.locator('[data-remove-draft]').click()
        expect(page.locator('#sp-confirm-title')).to_have_text('Retirer ce brouillon ?')
        page.locator('[data-confirm-dialog] [value=cancel]').click()
        assert not dialogs,dialogs
        assert not errors,errors
        browser.close()
