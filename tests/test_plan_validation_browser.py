import json
import os
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import SitePlan
from services.site_plan_import import import_pdf
from test_operations_live import live_operations
from test_site_plans import vector_pdf
from test_plan_corners import layout

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Browser opt-in')


def test_corner_checks_identify_other_arm_preserve_draft_and_approve(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    data=layout();a,b=data['panels']
    a.update(label='P12b',reviewed=True,warnings=['Possibile sbordo: controllare gli estremi rispetto al PDF'])
    b.update(label='P12a',reviewed=False,extent_confirmed=False)
    # Same geometry and width, but shifted from the original recognition.
    b['reference_points']=[[x,y-10] for x,y in b['points']]
    with Session(engine) as db:
        _,preview=import_pdf(vector_pdf())
        row=SitePlan(site_id=ids['site'],filename='corner-review.pdf',pdf_data=vector_pdf(),preview_data=preview,draft=json.dumps(data))
        db.add(row);db.commit();plan_id=row.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        url=origin+f'/manager/cantieri/{ids["site"]}/pianta';page.goto(url)
        expect(page.locator('[name=label]')).to_have_value('P12b')
        expect(page.locator('[name=reviewed]')).to_be_checked()
        expect(page.locator('[data-warnings]')).to_have_text('')
        expect(page.locator('[data-check-arm=b]')).to_contain_text('conferma gli estremi')
        expect(page.locator('[data-check-arm=b]')).to_contain_text('conferma sigla')
        page.locator('[data-approve]').click()
        expect(page.locator('[data-validation-summary]')).to_be_visible()
        expect(page.locator('[data-message]')).to_contain_text('P12a')
        expect(page.locator('[name=label]')).to_have_value('P12a')
        expect(page.locator('[data-reviewed-caption]')).to_contain_text('P12a')
        page.locator('[name=reviewed]').check()
        expect(page.locator('[data-validation-list]')).to_contain_text('estremi')
        expect(page.locator('[data-validation-list]')).not_to_contain_text('conferma sigla')
        with page.expect_response(lambda r:r.request.method=='PUT' and r.url.endswith('/bozza')) as saved:
            page.locator('[data-save]').click()
        assert saved.value.status==200
        expect(page.locator('[data-message]')).to_contain_text('Bozza salvata')
        with Session(engine) as db:
            row=db.get(SitePlan,plan_id);assert row.approved is None
            pending=json.loads(row.draft)['panels'][1];assert pending['reviewed'] and not pending['extent_confirmed']
        page.locator('[data-approve]').click()
        page.screenshot(path=str(artifacts/'corner-validation.png'),full_page=True)
        page.locator('[name=extent_confirmed]').check()
        expect(page.locator('[data-validation-summary]')).to_be_hidden()
        with page.expect_response(lambda r:r.request.method=='PUT' and r.url.endswith('/convalida')) as saved:
            page.locator('[data-approve]').click()
        assert saved.value.status==200,saved.value.text()
        expect(page.locator('[data-state]')).to_have_text('Disegno convalidato')
        with Session(engine) as db:
            panels=json.loads(db.get(SitePlan,plan_id).approved)['panels']
            assert all(p['reviewed'] for p in panels) and panels[1]['extent_confirmed']
            assert [p['points'] for p in panels]==[p['points'] for p in data['panels']]
        assert not errors,errors
        browser.close()


def test_bulk_review_reports_out_of_scale_branch_in_french(live_operations):
    origin,engine,ids,password,artifacts=live_operations
    data=layout();data['panels'][1]['width_m']=3
    with Session(engine) as db:
        _,preview=import_pdf(vector_pdf())
        db.add(SitePlan(site_id=ids['site'],filename='scale.pdf',pdf_data=vector_pdf(),preview_data=preview,draft=json.dumps(data)));db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page();page.on('dialog',lambda d:d.accept());errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com');page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click();page.wait_for_url('**/manager/dashboard')
        page.context.add_cookies([{'name':'lang','value':'fr','url':origin}])
        page.goto(origin+f'/manager/cantieri/{ids["site"]}/pianta')
        page.locator('[data-review-all-top]').click()
        expect(page.locator('[data-message]')).to_contain_text('P3b')
        expect(page.locator('[data-validation-list]')).to_contain_text('hors échelle')
        expect(page.locator('[name=label]')).to_have_value('P3b')
        expect(page.locator('[data-state]')).to_have_text('Brouillon à valider')
        assert not errors,errors
        browser.close()
