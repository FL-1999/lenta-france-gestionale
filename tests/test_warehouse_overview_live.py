import os
from datetime import date

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from auth import hash_password
from models import User, RoleEnum, MagazzinoItem, MagazzinoRichiesta, MagazzinoRichiestaPrioritaEnum
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')


def test_warehouse_overview_prices_and_role_access(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        warehouse = User(email='warehouse-overview@example.com', full_name='Magazziniere Collaudo',
                         role=RoleEnum.magazzino, hashed_password=hash_password(password), is_active=True)
        item = MagazzinoItem(nome='Acciaio per armature', codice='AC-01', unita_misura='kg', quantita_disponibile=100, costo_unitario=None, soglia_minima=120)
        db.add_all([warehouse, item]); db.flush()
        db.add(MagazzinoRichiesta(richiesto_da_user_id=warehouse.id, cantiere_id=ids['site'],
                                priorita=MagazzinoRichiestaPrioritaEnum.high, data_necessaria=date.today()))
        db.commit(); item_id = item.id
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        context = browser.new_context(viewport={'width':1440, 'height':1100}, reduced_motion='reduce')
        page = context.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin + '/') else r.abort())
        page.goto(origin + '/login')
        page.locator('#email').fill('smoke-manager@example.com'); page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click(); page.wait_for_url('**/manager/dashboard')
        page.goto(origin + '/manager/magazzino/dashboard')
        expect(page.get_by_role('heading', name='Il tuo magazzino')).to_be_visible()
        expect(page.locator('.wh-price-warning')).to_contain_text('1 costo da completare')
        for theme in ['dark', 'light']:
            if page.locator('html').get_attribute('data-theme') != theme:
                page.locator('#theme-toggle').click()
            for width in [1440, 390]:
                page.set_viewport_size({'width':width,'height':1100})
                expect(page.locator('.wh-shortcuts')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(artifacts / f'warehouse-overview-{theme}-{width}.png'), full_page=True)
        page.get_by_role('link', name='Prezzi e valorizzazione', exact=False).click()
        row = page.locator(f'[data-price-item="{item_id}"]')
        row.locator('[name=cost]').fill('-1')
        row.get_by_role('button', name='Salva costo').click()
        expect(page.get_by_role('alert')).to_contain_text('Inserisci un costo valido')
        expect(row.locator('[name=cost]')).to_have_value('-1')
        row.locator('[name=cost]').fill('0,20')
        row.get_by_role('button', name='Salva costo').click()
        expect(page.get_by_role('status')).to_contain_text('Costo aggiornato')
        expect(page.locator('[data-stock-value]')).to_have_text('€ 20.00')
        expect(row).to_contain_text('Disponibili: 100 kg')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=str(artifacts / 'warehouse-prices-mobile.png'), full_page=True)
        context.add_cookies([{'name':'lang','value':'fr','url':origin}]); page.reload()
        expect(page.get_by_role('heading', name='Prix et valorisation')).to_be_visible()
        expect(row.get_by_label('Coût unitaire · €/kg')).to_have_value('0.2')
        page.goto(origin + '/manager/magazzino/dashboard')
        expect(page.get_by_role('heading', name='Votre magasin')).to_be_visible()
        context.close()
        context = browser.new_context(viewport={'width':1440,'height':1100})
        page = context.new_page()
        context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(origin + '/') else r.abort())
        page.goto(origin + '/login'); page.locator('#email').fill('warehouse-overview@example.com')
        page.locator('#password').fill(password); page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/magazzino/dashboard')
        if page.locator('html').get_attribute('data-theme') != 'dark': page.locator('#theme-toggle').click()
        page.screenshot(path=str(artifacts / 'warehouse-role-dashboard.png'), full_page=True)
        page.goto(origin + '/manager/magazzino/prezzi')
        expect(page.locator('[name=cost]')).to_have_count(0)
        expect(page.get_by_text('0.2 €/kg', exact=True)).to_be_visible()
        assert not errors
        context.close(); browser.close()
    with Session(engine) as db:
        assert db.get(MagazzinoItem, item_id).quantita_disponibile == 100
