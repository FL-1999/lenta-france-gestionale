"""Shared shell exercised through real login for every role, desktop and phone."""
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from auth import hash_password
from models import Role, RoleEnum, Site, TrasportoViaggio, User, UserRole
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Live browser checks opt-in')


def test_workspace_roles_and_responsive_navigation(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        extra = {}
        for name in ('admin', 'driver', 'magazzino', 'ferraiolo'):
            user = User(email=f'workspace-{name}@example.com', full_name=f'Collaudo {name}',
                        role=RoleEnum(name), hashed_password=hash_password(password), is_active=True)
            db.add(user); db.flush(); extra[name] = user
        admin_role = db.query(Role).filter_by(name=RoleEnum.admin).one_or_none()
        driver_role = db.query(Role).filter_by(name=RoleEnum.driver).one_or_none()
        if not admin_role: admin_role = Role(name=RoleEnum.admin); db.add(admin_role)
        if not driver_role: driver_role = Role(name=RoleEnum.driver); db.add(driver_role)
        db.flush()
        extra['admin'].can_switch_roles = True
        db.add_all([UserRole(user_id=extra['admin'].id, role_id=admin_role.id),
                    UserRole(user_id=extra['admin'].id, role_id=driver_role.id)])
        trip = TrasportoViaggio(codice_viaggio='WORKSPACE-COLLAUDO', data_partenza=date.today(),
                               origine='Deposito prova', destinazione='Cantiere Collaudo',
                               autista_id=extra['driver'].id, destinazione_site_id=ids['site'])
        db.add(trip)
        db.get(Site, ids['site']).ferraiolo_id = extra['ferraiolo'].id
        db.commit(); trip_id = trip.id

    cases = [
        ('manager', 'smoke-manager@example.com', '/manager/dashboard', ['/manager/rapportini', '/manager/cantieri', '/capo/rapportini/nuovo', '/manager/fiches/nuova']),
        ('caposquadra', 'smoke-capo@example.com', '/capo/dashboard', ['/capo/rapportini', '/capo/rapportini/nuovo', '/capo/magazzino', '/capo/fiches/nuova']),
        ('driver', 'workspace-driver@example.com', '/driver/trasporti/viaggi', [f'/driver/trasporti/viaggi/{trip_id}', '/driver/trasporti/oggi']),
        ('magazzino', 'workspace-magazzino@example.com', '/manager/magazzino/dashboard', ['/manager/magazzino', '/manager/magazzino/richieste', '/manager/trasporti']),
        ('ferraiolo', 'workspace-ferraiolo@example.com', '/gabbie', [f"/gabbie/cantiere/{ids['site']}"]),
        ('admin', 'workspace-admin@example.com', '/manager/dashboard', ['/manager/utenti']),
    ]
    screenshots = Path(os.getenv('WORKSPACE_SCREENSHOTS', str(artifacts)))
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        errors, failures = [], []
        for role, email, home, pages in cases:
            context = browser.new_context(viewport={'width':1440, 'height':1000}, color_scheme='light')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: failures.append((response.status, response.url)) if response.status >= 500 else None)
            def intercept(route):
                if route.request.url.startswith(origin + '/'):
                    route.continue_()
                elif 'html5-qrcode' in route.request.url:
                    route.fulfill(content_type='application/javascript', body='window.Html5Qrcode = class { start() { return Promise.resolve(); } };')
                else: route.abort()
            page.route('**/*', intercept)
            page.goto(origin + '/login')
            page.locator('#email').fill(email)
            page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_url('**' + home)
            expect(page.locator('.workspace-frame')).to_have_attribute('data-role', role)
            expect(page.locator('.workspace-sidebar')).to_be_visible()
            expect(page.locator('.workspace-nav-link[aria-current=page]')).to_have_count(1)
            # Every navigation destination offered to this role must be accessible.
            for href in page.locator('.workspace-navigation a').evaluate_all('(links) => links.map(a => a.href)'):
                response = context.request.get(href)
                assert response.ok, (role, href, response.status)
            if role in ('driver', 'caposquadra', 'ferraiolo'):
                assert page.locator('.workspace-navigation a[href="/manager/utenti"]').count() == 0
            if role == 'driver':
                assert context.request.get(origin + '/manager/dashboard').status == 403
                assert page.locator('a[href="/manager/trasporti"]').count() == 0
            if role in ('manager', 'admin', 'caposquadra'):
                cards = page.locator('.module-card')
                assert cards.count() > 0
                # Visibility assertions alone do not detect opacity:0.
                for motion in ('reduce', 'no-preference'):
                    page.emulate_media(reduced_motion=motion)
                    assert cards.evaluate_all('(cards) => cards.every(c => getComputedStyle(c).opacity === "1" && c.getBoundingClientRect().height > 0)')
            if role in ('manager', 'admin'):
                expect(page.locator('.workspace-chart-empty')).to_have_count(3)
                expect(page.locator('#chartReportsLast30Days')).to_contain_text('Nessun dato')
                page.locator('.dashboard-modules-grid').screenshot(path=str(screenshots / f'{role}-cards.png'))
            page.screenshot(path=str(screenshots / f'{role}-desktop.png'))
            page.locator('#theme-toggle').click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            page.reload()
            expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
            page.screenshot(path=str(screenshots / f'{role}-dark.png'))
            page.locator('#theme-toggle').click()

            for width in (1024, 390, 320):
                page.set_viewport_size({'width':width, 'height':844})
                if width < 1024:
                    expect(page.locator('.workspace-sidebar')).to_be_hidden()
                    opener = page.locator('.workspace-topbar [data-workspace-toggle]')
                    opener.click()
                    expect(page.locator('.workspace-sidebar')).to_have_attribute('aria-modal', 'true')
                    expect(page.locator('.workspace-sidebar-close')).to_be_focused()
                    page.keyboard.press('Escape')
                    expect(opener).to_be_focused()
                    expect(page.locator('.workspace-sidebar')).to_be_hidden()
                    expect(page.locator('.workspace-bottom-nav')).to_be_visible()
                    assert not page.locator('.workspace-frame').evaluate('(el) => el.inert')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (role,width)
            page.set_viewport_size({'width':390, 'height':844})
            for path in pages:
                response = page.goto(origin + path)
                assert response.ok, (role, path, response.status)
                expect(page.locator('.workspace-topbar')).to_be_visible()
                expect(page.locator('.workspace-bottom-nav')).to_be_visible()
                # No actionable form control may be clipped outside the viewport.
                clipped = page.locator('main input:not([type=hidden]), main select, main button').evaluate_all('''els => els.filter(e => e.getClientRects().length && !e.closest('.workspace-table-scroll,.table-responsive,.table-wrapper,.technical-sheet')).filter(e => {const r=e.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth+1)}).map(e => e.id || e.name || e.textContent.slice(0,40))''')
                assert not clipped, (role, path, clipped)
                page.screenshot(path=str(screenshots / f'{role}-{urlsplit(path).path.replace("/", "-")}-mobile.png'))
            page.goto(origin + home)
            page.screenshot(path=str(screenshots / f'{role}-mobile.png'))
            # The lang attribute arrives before deferred navigation handlers.
            # Complete the actual navigation before clicking the next menu.
            with page.expect_navigation(wait_until='load'):
                page.locator('a[lang=fr]').click()
            expect(page.locator('html')).to_have_attribute('lang', 'fr')
            page.locator('.workspace-topbar [data-workspace-toggle]').click()
            expect(page.locator('.workspace-sidebar')).to_have_attribute('aria-label', 'Menu principal')
            expect(page.locator('.workspace-sidebar')).to_have_attribute('aria-modal', 'true')
            page.keyboard.press('Escape')
            expect(page.locator('.workspace-topbar [data-workspace-toggle]')).to_have_attribute('aria-expanded', 'false')
            account = page.get_by_role('button', name='Menu du compte')
            account.click()
            expect(account).to_have_attribute('aria-expanded', 'true')
            if role == 'admin':
                page.locator('a[href="/switch-role/driver"]').click()
                page.wait_for_url('**/driver/trasporti/viaggi')
                expect(page.locator('.workspace-frame')).to_have_attribute('data-role', 'driver')
                assert page.locator('.workspace-navigation a[href="/manager/utenti"]').count() == 0
                page.get_by_role('button', name='Menu du compte').click()
            page.get_by_role('link', name='Déconnexion', exact=True).click()
            page.wait_for_url('**/login')
            context.close()
        assert not errors, errors
        assert not failures, failures
        browser.close()
