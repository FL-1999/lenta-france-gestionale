"""Real manager session: bell -> alert -> explicit validation, on desktop and phone."""
import os
from datetime import date
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Fiche, FicheTypeEnum, FicheConsumptionAlert, User
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_manager_bell_validation_and_site_summary(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        rows=[]
        for panel, actual in [(1,15),(2,25)]:
            f=Fiche(site_id=ids['site'], created_by_id=manager.id, date=date(2026,10,22),
                numero_pannello=panel,panel_name=f'P{panel}',fiche_type=FicheTypeEnum.produzione,
                description='Collaudo consumo',tipologia_scavo='paratia',profondita_totale=10,
                larghezza_pannello=2,altezza_pannello=1,quota_partenza=15,quota_tn=16,
                metri_cubi_gettati=actual)
            db.add(f);rows.append(f)
        db.commit();fid=rows[0].id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        page=context.new_page(); errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password);page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        expect(page.locator('#notificationCount')).to_have_text('2')
        if page.locator('html').get_attribute('data-theme')!='dark':page.locator('#theme-toggle').click()
        page.locator('#notificationsToggle').click()
        expect(page.locator('.notification-item--alert')).to_have_count(2)
        page.locator('[data-notifications-mark-all]').click()
        expect(page.locator('#notificationCount')).to_have_text('2')
        page.locator('[data-notifications-clear-all]').click()
        expect(page.locator('.notification-item--alert')).to_have_count(2)
        page.screenshot(path=str(out/'consumption-bell-desktop.png'))
        page.get_by_role('link',name='Consumo calcestruzzo').filter(has_text='P1').click()
        page.wait_for_url(f'**/manager/fiches/{fid}#fiche-consumption')
        expect(page.locator('#notificationCount')).to_have_text('2')
        expect(page.locator('#fiche-consumption')).to_contain_text('5,00 m³ in meno')
        expect(page.locator('#fiche-consumption')).to_have_class('kpi-card kpi-card--consumption-alert')
        expect(page.locator('#fiche-consumption')).to_have_css('background-color','rgb(64, 36, 42)')
        page.locator('.dashboard-kpi-grid').screenshot(path=str(out/'consumption-kpi.png'))
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':844 if width<1000 else 1000})
            page.locator('[data-consumption-review]').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            expect(page.get_by_role('button',name='Valida consumo',exact=True)).to_be_visible()
            page.screenshot(path=str(out/f'consumption-review-{width}.png'))
        page.get_by_role('button',name='Valida consumo',exact=True).click()
        expect(page.locator('#notificationCount')).to_have_text('1')
        expect(page.locator('.kpi-card--consumption-alert')).to_have_count(0)
        expect(page.locator('[data-consumption-reviewed]')).to_contain_text('Manager Collaudo')
        with Session(engine) as db:
            assert db.get(Fiche,fid).metri_cubi_gettati==15
            assert db.get(FicheConsumptionAlert,fid).status=='validated'
        page.goto(origin+f'/manager/cantieri/{ids["site"]}#site-consumption')
        expect(page.locator('#site-consumption')).to_contain_text('Anomalie validate: 1')
        expect(page.locator('.consumption-pending li')).to_have_count(1)
        expect(page.locator('.consumption-pending li')).to_contain_text('P2')
        for width in (390,1440):
            page.set_viewport_size({'width':width,'height':844 if width==390 else 1000})
            page.locator('#site-consumption').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/f'consumption-site-{width}.png'))
        assert not errors, errors
        browser.close()
