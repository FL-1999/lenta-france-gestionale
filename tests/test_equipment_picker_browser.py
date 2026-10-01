import os

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from models import Site, SiteCoupe, SiteProgressGridName, SiteSpecialEquipmentConfig
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_add_equipment_to_multiple_panels_preserves_other_controls(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        db.get(Site, ids['site']).numero_totale_paratie = 3
        db.add(SiteCoupe(site_id=ids['site'], nome='Coupe existante', tipologia_scavo='paratia'))
        for n, label in [(1, 'P10'), (2, 'P2'), (3, 'P7A')]:
            db.add(SiteProgressGridName(site_id=ids['site'], tipologia_scavo='paratia', numero_elemento=n, nome_personalizzato=label))
        db.add(SiteSpecialEquipmentConfig(site_id=ids['site'], tipologia_scavo='paratia', numero_elemento=1, inclinometre_previsto=True))
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page.goto(origin + '/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        page.context.add_cookies([{'name': 'lang', 'value': 'fr', 'url': origin}])
        config = origin + f'/manager/cantieri/{ids["site"]}/configurazione-progetto'
        page.goto(config)
        expect(page.locator('.project-equipment-row:not(.project-equipment-row--head) span').first).to_have_text('P10')
        page.locator('[data-add-equipment=sonic]').first.click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('[data-equipment-apply]')).to_be_disabled()
        expect(dialog.locator('[data-equipment-options] label')).to_have_text(['P2', 'P7A', 'P10'])
        dialog.get_by_role('checkbox', name='P2', exact=True).check()
        dialog.get_by_role('checkbox', name='P10', exact=True).check()
        dialog.locator('[data-equipment-apply]').click()
        expect(page.locator('[data-equipment-feedback]')).to_contain_text('P2, P10')
        modes = page.locator('[name=equipment_mode]')
        expect(modes.nth(0)).to_have_value('sonic_inclinometre')
        expect(modes.nth(1)).to_have_value('sonic')
        expect(modes.nth(2)).to_have_value('aucun')
        page.locator('[data-add-equipment=sonic]').first.click()
        expect(dialog.get_by_role('checkbox', name='P10')).to_be_disabled()
        dialog.get_by_role('checkbox', name='P7A', exact=True).check()
        dialog.locator('[data-equipment-cancel]').click()
        expect(modes.nth(2)).to_have_value('aucun')
        page.locator('[data-add-equipment=inclinometre]').first.click()
        dialog.locator('[data-equipment-search]').fill('P2')
        dialog.locator('[data-equipment-all]').click()
        expect(dialog.locator('[data-equipment-count]')).to_have_text('1 panneaux sélectionnés')
        dialog.locator('[data-equipment-clear]').click()
        expect(dialog.locator('[data-equipment-apply]')).to_be_disabled()
        dialog.locator('[data-equipment-all]').click()
        dialog.locator('[data-equipment-apply]').click()
        expect(modes.nth(1)).to_have_value('sonic_inclinometre')
        page.locator('.project-sticky-actions button[type=submit]').click()
        page.wait_for_url('**/configurazione-progetto?saved=1')
        with Session(engine) as db:
            equipment = db.query(SiteSpecialEquipmentConfig).filter_by(site_id=ids['site']).all()
            assert {r.numero_elemento: (r.sonic_previsto, r.inclinometre_previsto) for r in equipment} == {1: (True, True), 2: (True, True)}
            assert db.query(SiteCoupe).filter_by(site_id=ids['site']).one().nome == 'Coupe existante'
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('[data-add-equipment=inclinometre]').first.click()
        expect(dialog.get_by_role('checkbox', name='P2')).to_be_disabled()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(artifacts / 'equipment-picker-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.screenshot(path=str(artifacts / 'equipment-picker-desktop.png'), full_page=True)
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        assert not errors, errors
        browser.close()
