import json
import os
from datetime import date

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Fiche, FicheTypeEnum, Site, SitePour, SitePourPanel, User
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')


def test_physical_progress_desktop_and_phone(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        site=db.get(Site,ids['site']);site.numero_totale_paratie=3
        manager=db.query(User).filter_by(email='smoke-manager@example.com').one()
        f=Fiche(site_id=site.id,created_by_id=manager.id,date=date(2026,10,22),
            numero_pannello=1,panel_name='P7 A/B',fiche_type=FicheTypeEnum.produzione,
            description='Collaudo angolo',tipologia_scavo='paratia',profondita_totale=10,
            larghezza_pannello=5,altezza_pannello=.5,metri_cubi_gettati=27,review_status='confirmed')
        group=SitePour(site_id=site.id,kind='angle',label='P7 A/B')
        for n,width in [(1,2),(2,3)]:
            group.members.append(SitePourPanel(site_id=site.id,number=n,label=f'P7{"A" if n==1 else "B"}',
                fiche=f,snapshot=json.dumps(dict(width=width,depth=10,thickness=.5,coupe_id=None,coupe='Coupe test'))))
        db.add(group);db.commit()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login');page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password);page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin+f'/manager/cantieri/{ids["site"]}#site-panel-progress')
        card=page.locator('#site-panel-progress')
        expect(card).to_contain_text('1 / 2')
        expect(card).to_contain_text('50,00')
        expect(card).to_contain_text('27,00')
        expect(card.get_by_role('progressbar')).to_have_attribute('aria-valuenow','50')
        if page.locator('html').get_attribute('data-theme')!='dark': page.locator('#theme-toggle').click()
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':844 if width<1000 else 1000})
            card.scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            expect(card).to_be_visible()
            page.screenshot(path=str(out/f'panel-progress-{width}.png'))
        assert not errors,errors
        browser.close()
