"""Exercise the shared theme on real module pages, including older inline styles.

All requests use a disposable DB. Exported PDF/QR paper is intentionally separate
from app chrome; its legibility is covered by existing technical-sheet tests.
"""
import os
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from models import Report, RoleEnum, User
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Live browser checks opt-in')


def test_module_pages_day_night_and_phone(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
        db.add(User(email='glass-admin@example.com', full_name='Collaudo interfaccia',
                    hashed_password=manager.hashed_password, role=RoleEnum.admin, is_active=True))
        db.commit()
    paths = [
        '/manager/cantieri', '/manager/cantieri/nuovo',
        f"/manager/cantieri/{ids['site']}", f"/manager/cantieri/{ids['site']}/modifica",
        f"/manager/cantieri/{ids['site']}/configurazione-progetto",
        f"/manager/cantieri/{ids['site']}/documenti", f"/manager/cantieri/{ids['site']}/economics",
        f"/manager/cantieri/{ids['site']}/avanzamento-griglie",
        '/manager/note-operative', '/manager/note-operative/storico',
        '/manager/fiches', '/manager/fiches/nuova', '/manager/rapportini',
        '/manager/dashboard/produzione', '/manager/report/produzione', '/manager/report', '/manager/economics',
        '/manager/macchinari', '/manager/macchinari/nuovo', '/manager/macchinari/tipologie',
        f"/manager/macchinari/{ids['machine']}", f"/manager/macchinari/{ids['machine']}/modifica",
        '/manager/veicoli', '/manager/veicoli/nuovo',
        '/manager/attrezzature', '/manager/attrezzature/nuova', '/manager/depositi', '/manager/depositi/nuovo',
        '/manager/personale', '/manager/personale/new', f"/manager/personale/{ids['person']}/edit",
        '/manager/personale/presenze', '/manager/utenti', '/manager/utenti/nuovo',
        '/manager/magazzino', '/manager/magazzino/dashboard', '/manager/magazzino/nuovo',
        '/manager/magazzino/richieste', '/manager/magazzino/archiviati', '/manager/magazzino/sotto-soglia',
        '/manager/magazzino/movimenti', f"/manager/magazzino/report-consumi?cantiere_id={ids['site']}", '/manager/magazzino/categorie',
        '/manager/magazzino/categorie/nuova', '/manager/magazzino/macros', '/manager/magazzino/macro/nuova',
        '/manager/fornitori', '/manager/fornitori/nuovo', '/manager/ordini', '/manager/ordini/nuovo',
        '/manager/trasporti', '/manager/trasporti/nuovo', '/manager/trasporti/planner', '/manager/trasporti/mappa',
        '/manager/trasporti/attrezzature-in-viaggio', '/manager/trasporti/movimenti',
        '/operazioni', '/operazioni/pianificazione', f"/operazioni/documenti/{ids['doc']}",
        '/gabbie', f"/gabbie/cantiere/{ids['site']}", '/admin/audit', '/admin/backup-export', '/admin/permessi-magazzino',
    ]
    screenshots = Path(os.getenv('WORKSPACE_SCREENSHOTS', str(artifacts)))
    screenshots.mkdir(parents=True, exist_ok=True)
    captures = ['configurazione-progetto', '/economics', '/ordini/nuovo', '/trasporti/nuovo', '/fiches/nuova', '/personale/presenze']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width':1440,'height':1000}, color_scheme='light')
        page.emulate_media(reduced_motion='reduce')
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page.goto(origin+'/login')
        page.locator('#email').fill('glass-admin@example.com')
        page.locator('#password').fill(password)
        page.locator('#login-form button[type=submit]').click()
        page.wait_for_url('**/manager/dashboard')
        for path in paths:
            response=page.goto(origin+path)
            assert response.ok,(path,response.status,(artifacts/'server.log').read_text(encoding='utf-8',errors='replace')[-7000:])
            expect(page.locator('.workspace-topbar')).to_be_visible()
            assert page.locator('link[href*="workspace.css"]').count()==1,path
            for theme,background in [('light','rgb(228, 228, 223)'),('dark','rgb(11, 25, 43)')]:
                if page.locator('html').get_attribute('data-theme')!=theme:
                    page.locator('#theme-toggle').click()
                expect(page.locator('html')).to_have_attribute('data-theme',theme)
                assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')==background,path
                assert page.locator('main .card').evaluate_all('(els)=>els.filter(e=>e.getClientRects().length).every(e=>getComputedStyle(e).opacity==="1")'),path
                if any(path.endswith(part) for part in captures):
                    page.screenshot(path=str(screenshots/f'coverage-{path.replace("/","-")}-{theme}.png'))
            page.set_viewport_size({'width':390,'height':844})
            clipped=page.locator('main input:not([type=hidden]),main select,main button').evaluate_all('''els=>els.filter(e=>e.getClientRects().length && !e.closest('.workspace-table-scroll,.table-responsive,.table-wrapper,.technical-sheet,.planner-week')).filter(e=>{const r=e.getBoundingClientRect();return r.width&&(r.left< -1||r.right>innerWidth+1)}).map(e=>e.id||e.name||e.textContent.slice(0,30))''')
            assert not clipped,(path,clipped)
            page.set_viewport_size({'width':1440,'height':1000})
        # A populated dashboard must also update its chart colours on theme
        # switch. Stub only the external renderer, leaving real page data and
        # application JS intact so this contract check works offline in CI.
        with Session(engine) as db:
            manager = db.query(User).filter_by(email='smoke-manager@example.com').one()
            db.add(Report(date=date.today(),site_id=ids['site'],site_name_or_code='Cantiere Collaudo',
                          total_hours=7,workers_count=1,created_by_id=manager.id))
            db.commit()
        page.route('https://cdn.jsdelivr.net/npm/apexcharts',lambda route:route.fulfill(
            content_type='application/javascript',body='''window.__charts=[];window.ApexCharts=class {
            constructor(target,options){this.initial=options;this.latest=options;window.__charts.push(this)}
            render(){return Promise.resolve()} updateOptions(options){this.latest=options;return Promise.resolve()}
            };'''))
        page.goto(origin+'/manager/dashboard')
        page.wait_for_function('window.__charts?.length === 3')
        expect(page.locator('#kpiReports30Days')).to_have_text('1')
        for mode in ('light','dark'):
            if page.locator('html').get_attribute('data-theme')!=mode:
                page.locator('#theme-toggle').click()
            page.wait_for_function('window.__charts.every(c => c.latest.chart.foreColor === getComputedStyle(document.documentElement).getPropertyValue("--ws-ink").trim())')
            assert page.evaluate('window.__charts.every(c => c.latest.tooltip.theme === document.documentElement.dataset.theme)')
        assert not errors,errors
        browser.close()
