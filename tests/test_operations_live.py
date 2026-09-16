"""Release smoke test over real HTTP, cookies and a disposable database.

Runs with RUN_BROWSER_TESTS=1. No authentication or request overrides.
The only startup shortcut skips downloading the unrelated PDF browser.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from datetime import date

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

import main  # Registers all application models.
from auth import hash_password
from models import (Base, DocumentVersion, Machine, PersonalePresenza, Report,
                    ReportDraft, ReportReview, ResourcePlan, RoleEnum, Site,
                    SiteDocument, SiteDocumentCategoryEnum, User)
from routers.reports import ensure_capo_personale


pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Live browser checks opt-in')
NEW_TABLES = {'report_drafts', 'report_reviews', 'report_review_events', 'resource_plans', 'document_versions'}


@pytest.fixture
def live_operations(tmp_path):
    database_url = 'sqlite:///' + (tmp_path / 'release-smoke.db').as_posix()
    engine = create_engine(database_url)
    combined = MetaData()
    for metadata in (Base.metadata, SQLModel.metadata):
        for table in metadata.tables.values():
            if table.name not in combined.tables and table.name not in NEW_TABLES:
                table.to_metadata(combined)
    combined.create_all(engine)
    assert not NEW_TABLES.intersection(inspect(engine).get_table_names())
    password = 'Disposable-smoke-test-only-2026'
    with Session(engine) as db:
        manager = User(email='smoke-manager@example.com', full_name='Manager Collaudo', role=RoleEnum.manager,
                       hashed_password=hash_password(password), is_active=True)
        capo = User(email='smoke-capo@example.com', full_name='Capo Collaudo', role=RoleEnum.caposquadra,
                    hashed_password=hash_password(password), is_active=True)
        db.add_all([manager, capo]); db.flush()
        site = Site(name='Cantiere Collaudo', caposquadra_id=capo.id, is_active=True)
        other = Site(name='Altro Cantiere Collaudo', is_active=True)
        machine = Machine(name='Macchina Collaudo', is_active=True)
        db.add_all([site, other, machine]); db.flush()
        person = ensure_capo_personale(db, capo)
        doc = SiteDocument(site_id=site.id, filename='originale.txt', data=b'originale conservato',
                           size_bytes=20, content_type='text/plain', category=SiteDocumentCategoryEnum.documento,
                           uploaded_by_id=manager.id)
        db.add(doc); db.commit()
        ids = {'site': site.id, 'other': other.id, 'machine': machine.id, 'person': person.id, 'doc': doc.id}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = os.environ.copy()
    env.update(DATABASE_URL=database_url, APP_ENV='test', SECRET_KEY='isolated-live-smoke-secret-only', RENDER='false')
    for key in ('ADMIN_EMAIL', 'ADMIN_PASSWORD', 'TEST_POSTGRES_URL'):
        env.pop(key, None)
    command = ('import main, uvicorn; main._CHROMIUM_INSTALL_TRIED = True; '
               f'uvicorn.run(main.app, host="127.0.0.1", port={port})')
    log_path = tmp_path / 'server.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-c', command], env=env,
                                   cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text(encoding='utf-8')
                try:
                    if httpx.get(origin + '/login', timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.2)
            else:
                pytest.fail(log_path.read_text(encoding='utf-8'))
            assert NEW_TABLES.issubset(inspect(engine).get_table_names())
            yield origin, engine, ids, password, tmp_path
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=10)
            engine.dispose()


def test_live_release_workflows(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        capo_context = browser.new_context(viewport={'width': 390, 'height': 844})
        manager_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        capo, manager = capo_context.new_page(), manager_context.new_page()
        errors, failures = [], []
        for page in (capo, manager):
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: failures.append((response.status, response.url)) if response.status >= 500 else None)
            # Keep this test independent of third-party CDNs; local assets use real HTTP.
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())

        def login(page, email, destination):
            page.goto(origin + '/login')
            page.locator('#email').fill(email)
            page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_url('**' + destination)

        login(capo, 'smoke-capo@example.com', '/capo/dashboard')
        login(manager, 'smoke-manager@example.com', '/manager/dashboard')
        assert httpx.get(origin + '/operazioni', follow_redirects=False).status_code in (303, 307, 401)

        capo.goto(origin + '/capo/rapportini/nuovo')
        expect(capo.locator('#draft-status')).to_contain_text('Le modifiche saranno salvate')
        capo.locator('#data').fill('2026-09-16')
        capo.locator('#cantiere_id').select_option(str(ids['site']))
        capo.locator('#attivita').fill('Attività del collaudo pratico')
        expect(capo.locator('#draft-status')).to_contain_text('Bozza salvata alle')
        capo.reload()
        expect(capo.locator('#draft-status')).to_contain_text('Bozza ripristinata')
        expect(capo.locator('#attivita')).to_have_value('Attività del collaudo pratico')
        with Session(engine) as db:
            assert db.query(Report).count() == db.query(PersonalePresenza).count() == 0
        capo.locator('#rapportino-form button[type=submit]').click()
        capo.wait_for_url('**/capo/dashboard?rapportino_created=1')
        with Session(engine) as db:
            report_id = db.query(Report).one().id
            assert db.query(ReportDraft).one().payload == 'null'
        review_url = origin + f'/operazioni/rapportini/{report_id}'
        manager.goto(review_url)
        manager.locator('#review-note').fill('Precisare attività e ore')
        with manager.expect_navigation(wait_until='domcontentloaded'):
            manager.get_by_role('button', name='Richiedi correzione', exact=True).click()
        expect(manager.locator('.page-header')).to_contain_text('Da correggere')
        capo.goto(origin + '/operazioni')
        expect(capo.locator(f'a[href="/operazioni/rapportini/{report_id}"]')).to_be_visible()
        capo.goto(review_url)
        capo.locator('summary').click()
        capo.locator('[name=activities]').fill('Attività corrette dopo la verifica')
        capo.locator('[name=total_hours]').fill('7')
        capo.locator('[data-worker-id]').fill('7')
        with capo.expect_navigation(wait_until='domcontentloaded'):
            capo.get_by_role('button', name='Salva correzioni', exact=True).click()
        with capo.expect_navigation(wait_until='domcontentloaded'):
            capo.get_by_role('button', name='Rinvia alla verifica', exact=True).click()
        manager.goto(review_url)
        expect(manager.locator('.card').first).to_contain_text('Attività corrette dopo la verifica')
        with manager.expect_navigation(wait_until='domcontentloaded'):
            manager.get_by_role('button', name='Valida', exact=True).click()
        expect(manager.locator('.page-header')).to_contain_text('Validato')
        expect(manager.locator('[data-report-edit]')).to_have_count(0)
        capo.reload()
        expect(capo.locator('[data-report-edit]')).to_have_count(0)
        with Session(engine) as db:
            assert db.get(ReportReview, report_id).status == 'approved'
            assert db.get(Report, report_id).total_hours == 7
            attendance_count = db.query(PersonalePresenza).count()

        manager.goto(origin + '/operazioni/pianificazione?week=2026-09-16')
        form = manager.locator('form[action="/operazioni/pianificazione"]')
        def assign(resource, site):
            form.locator('[name=day]').fill('2026-09-16')
            form.locator('[name=site_id]').select_option(str(site))
            form.locator('[name=resource]').select_option(resource)
        for resource in (f"person:{ids['person']}", f"machine:{ids['machine']}"):
            assign(resource, ids['site'])
            with manager.expect_navigation(wait_until='domcontentloaded'):
                form.get_by_role('button').click()
        expect(manager.locator('.ops-plan')).to_have_count(2)
        assign(f"machine:{ids['machine']}", ids['other'])
        form.get_by_role('button').click()
        expect(form.locator('[data-ops-error]')).to_contain_text('Risorsa già pianificata')
        with Session(engine) as db:
            assert db.query(ResourcePlan).count() == 2
            assert db.query(PersonalePresenza).count() == attendance_count
        capo.goto(origin + '/operazioni/pianificazione?week=2026-09-16')
        expect(capo.locator('.ops-plan')).to_have_count(2)
        expect(capo.locator('[name=resource]')).to_have_count(0)

        manager.goto(origin + f"/operazioni/documenti/{ids['doc']}")
        manager.locator('[name=file]').set_input_files({'name': 'revisione.txt', 'mimeType': 'text/plain', 'buffer': b'nuova revisione del collaudo'})
        manager.locator('[name=expires_on]').fill(date.today().isoformat())
        with manager.expect_navigation(wait_until='domcontentloaded'):
            manager.get_by_role('button', name='Salva nuova revisione').click()
        expect(manager.locator('.alert-info')).to_contain_text('revisione.txt')
        with Session(engine) as db:
            version = db.query(DocumentVersion).one()
            assert version.number == 2
            revised_id = version.document_id
        assert manager_context.request.get(origin + f"/manager/documenti/{ids['doc']}/download").body() == b'originale conservato'
        assert manager_context.request.get(origin + f'/manager/documenti/{revised_id}/download').body() == b'nuova revisione del collaudo'
        manager.goto(origin + '/operazioni')
        expect(manager.get_by_role('link', name='revisione.txt', exact=True)).to_be_visible()
        manager.screenshot(path=str(artifacts / 'oggi-desktop.png'), full_page=True)
        capo.goto(origin + '/operazioni')
        expect(capo.get_by_role('heading', name='Rapportini da controllare')).to_be_visible()
        capo.screenshot(path=str(artifacts / 'oggi-mobile.png'), full_page=True)
        assert not errors, errors
        assert not failures, failures
        browser.close()
