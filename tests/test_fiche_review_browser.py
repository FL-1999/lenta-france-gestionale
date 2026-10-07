"""Real cookie session and responsive login/review regression."""
import os
from datetime import date
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import User, Role, UserRole, RoleEnum, Fiche, FicheTypeEnum, Site
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_login_layout_and_fiche_review(live_operations):
    origin, engine, ids, password, out = live_operations
    with Session(engine) as db:
        user=db.query(User).filter_by(email='smoke-manager@example.com').one()
        user.role=RoleEnum.admin
        role=db.query(Role).filter_by(name='admin').one()
        db.add(UserRole(user_id=user.id,role_id=role.id))
        site=db.get(Site,ids['site']);site.numero_totale_paratie=4
        f=Fiche(site_id=site.id,created_by_id=user.id,date=date.today(),numero_pannello=2,
            panel_name='2 A',fiche_type=FicheTypeEnum.produzione,description='Scavo',
            tipologia_scavo='paratia',review_status='pending')
        db.add(f);db.commit();fid=f.id
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page=browser.new_page()
        page.goto(origin+'/login')
        for width in (1440,390,320):
            page.set_viewport_size({'width':width,'height':900})
            email=page.locator('#email').bounding_box();password_box=page.locator('#password').bounding_box()
            assert email['y']+email['height'] < password_box['y']
            assert abs(email['x']-password_box['x']) < 1
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            expect(page.get_by_role('button',name='Entra',exact=True)).to_be_visible()
            page.screenshot(path=str(out/f'login-{width}.png'))
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.get_by_role('button',name='Entra',exact=True).click()
        page.wait_for_url('**/manager/dashboard')
        page.goto(origin+'/manager/fiches?review_status=pending')
        expect(page.get_by_role('cell',name='2 A Da verificare')).to_be_visible()
        page.get_by_role('link',name='Apri',exact=True).click()
        expect(page.locator('.fiche-review-banner')).to_contain_text('Da verificare')
        page.get_by_role('button',name='Conferma fiche',exact=True).click()
        expect(page.locator('.fiche-review-banner')).to_contain_text('Confermata')
        expect(page.get_by_role('button',name='Conferma fiche',exact=True)).to_have_count(0)
        with Session(engine) as db:
            assert db.get(Fiche,fid).review_status=='confirmed'
            assert db.get(Site,ids['site']).paratie_done_panels==1
        browser.close()
