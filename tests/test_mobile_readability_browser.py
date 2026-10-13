"""Phone layouts with realistic names and actual forms, on an isolated database."""
import os
from datetime import date, timedelta

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from models import Personale, PersonalePresenza, User
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_phone_readability_and_attendance_workflow(live_operations):
    origin, engine, ids, password, out = live_operations
    monday = date.today() - timedelta(days=date.today().weekday())
    with Session(engine) as db:
        manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
        person = Personale(nome='Giovanni', cognome='De Santis', ruolo='meccanico / operatore',
                           email='giovanni.desantis@example.com', telefono='+33 6 12 34 56 78', attivo=True)
        own = Personale(nome='Marco', cognome='Responsabile', user_id=manager.id, attivo=True)
        db.add_all([person, own]); db.flush()
        db.add(PersonalePresenza(personale_id=person.id, attendance_date=monday, status='WORK',
                                site_id=ids['site'], hours=8))
        db.commit(); person_id = person.id
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True,
                                reduced_motion='reduce')
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page.goto(origin+'/login')
        page.locator('#email').fill('smoke-manager@example.com'); page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click(); page.wait_for_url('**/manager/dashboard')
        cases = {
            'dashboard': '/manager/dashboard',
            'personale': '/manager/personale',
            'presenze': f'/manager/personale/presenze?week_start={monday}',
            'mensile': f'/manager/personale/presenze?view=month&report_type=employee&personale_id={person_id}&month={monday:%Y-%m}',
            'scheda': f'/manager/personale/{person_id}/edit',
            'spazio': '/mio-spazio',
            'squadre': '/manager/personale/squadre',
            'rapportino': '/capo/rapportini/nuovo',
            'fiches': '/manager/fiches/nuova',
            'cantieri': '/manager/cantieri',
        }
        for width in [390, 320]:
            page.set_viewport_size({'width':width, 'height':844})
            for name, path in cases.items():
                assert page.goto(origin+path).ok, path
                if name in ('spazio', 'squadre'):
                    expect(page.locator('#pw-content')).not_to_have_text('Caricamento…')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, name)
                squeezed = page.locator('main h1, main h2, main p, main .btn, main label').evaluate_all('''els => els.filter(e => {
                  const r = e.getBoundingClientRect();
                  return r.width > 0 && r.width < 125 && r.height > 60 && e.innerText.trim().split(/\\s+/).length >= 4;
                }).map(e => e.innerText.slice(0,120))''')
                assert not squeezed, (width, name, squeezed)
                clipped = page.locator('main input:not([type=hidden]), main select, main textarea, main .btn').evaluate_all('''els => els.filter(e => {
                  if (!e.getClientRects().length || e.closest('.workspace-table-scroll:not(:has(.attendance-table)):not(:has(.personnel-name)),.technical-sheet')) return false;
                  const r=e.getBoundingClientRect(); return r.width && (r.left < -1 || r.right > innerWidth+1);
                }).map(e => e.name || e.textContent.slice(0,40))''')
                assert not clipped, (width, name, clipped)
                if name in ('personale', 'presenze'):
                    rows = page.locator('main .data-table tbody tr')
                    assert rows.evaluate_all('(rows)=>rows.every(e=>e.scrollWidth<=e.clientWidth+1)')
                if width == 390:
                    page.screenshot(path=str(out/f'{name}-390.png'), full_page=True)
        # Filter one person, expand a day and save actual hours from the phone.
        page.goto(origin+cases['presenze'])
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('.week-selector button[type=submit]').click()
        expect(page.locator('.attendance-table tbody tr')).to_have_count(3)
        page.locator('.week-selector [name=personale_id]').select_option(str(person_id))
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('.week-selector button[type=submit]').click()
        expect(page.locator('.attendance-table tbody tr')).to_have_count(1)
        row = page.locator('.attendance-table tbody tr')
        expect(row).to_contain_text('De Santis Giovanni')
        editor = row.locator('.attendance-editor').nth(1)
        editor.locator('summary').click()
        form = editor.locator('form')
        form.locator('[name=status]').select_option('WORK')
        form.locator('[name=site_id]').select_option(str(ids['site']))
        form.locator('[name=hours]').fill('7.5')
        assert form.bounding_box()['width'] >= 240
        assert form.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.screenshot(path=str(out/'presenza-modifica-320.png'), full_page=True)
        with page.expect_navigation(wait_until='domcontentloaded'):
            form.locator('[type=submit]').click()
        expect(page.locator('.attendance-table tbody tr')).to_have_count(1)
        with Session(engine) as db:
            saved = db.query(PersonalePresenza).filter_by(personale_id=person_id, attendance_date=monday+timedelta(days=1)).one()
            assert saved.status == 'WORK' and saved.hours == 7.5 and saved.site_id == ids['site']
            assert db.query(PersonalePresenza).filter_by(personale_id=person_id).count() == 2
        # At desktop widths the same records are still a weekly table.
        page.set_viewport_size({'width':1440, 'height':1000})
        assert page.locator('.attendance-table').evaluate('(e)=>getComputedStyle(e).display') == 'table'
        expect(page.locator('.attendance-table thead')).to_be_visible()
        page.screenshot(path=str(out/'presenze-desktop.png'), full_page=True)
        # French labels and the dark theme share the usable phone layout.
        page.set_viewport_size({'width':390, 'height':844})
        with page.expect_navigation(wait_until='load'):
            page.locator('a[lang=fr]').click()
        page.locator('#theme-toggle').click()
        expect(page.locator('html')).to_have_attribute('data-theme','dark')
        expect(page.locator('.attendance-table')).to_contain_text('+ Ajouter')
        assert page.locator('.attendance-table').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.screenshot(path=str(out/'presenze-fr-dark.png'), full_page=True)
        assert not errors, errors
        print('MOBILE_SCREENSHOTS='+str(out))
        browser.close()
