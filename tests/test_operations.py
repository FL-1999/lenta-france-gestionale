from datetime import date
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, MetaData
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import main
import template_context
from auth import get_current_active_user_api, get_current_active_user_html
from database import get_db
from models import (Base, DocumentVersion, Machine, Personale, PersonalePresenza, Report,
                    ReportDraft, ReportReview, ResourcePlan, RoleEnum, Site, SiteDocument,
                    SiteDocumentCategoryEnum, SiteTask, User)
from routers.reports import ensure_capo_personale


@pytest.fixture
def operations(monkeypatch):
    postgres_url = os.getenv('TEST_POSTGRES_URL')
    combined = None
    if postgres_url:
        parsed = make_url(postgres_url)
        assert parsed.host in {'127.0.0.1', 'localhost'} and parsed.database == 'lenta_operations_test', 'Only the dedicated local CI test database is allowed'
        engine = create_engine(postgres_url)
        combined = MetaData()
        for metadata in (Base.metadata, SQLModel.metadata):
            for table in metadata.tables.values():
                if table.name not in combined.tables:
                    table.to_metadata(combined)
        combined.create_all(engine)
    else:
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        SQLModel.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    admin = User(email='operations-manager@example.com', full_name='Responsabile', role=RoleEnum.manager, hashed_password='x', is_active=True)
    capo = User(email='operations-capo@example.com', full_name='Capo Test', role=RoleEnum.caposquadra, hashed_password='x', is_active=True)
    outsider = User(email='operations-other@example.com', full_name='Altro Capo', role=RoleEnum.caposquadra, hashed_password='x', is_active=True)
    db.add_all([admin, capo, outsider]); db.flush()
    site = Site(name='Cantiere assegnato', caposquadra_id=capo.id, is_active=True)
    other = Site(name='Cantiere riservato', caposquadra_id=outsider.id, is_active=True)
    db.add_all([site, other]); db.flush()
    person = ensure_capo_personale(db, capo)
    machine = Machine(name='Macchina prova', is_active=True)
    db.add(machine); db.commit()
    actor = [capo]
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[get_current_active_user_api] = lambda: actor[0]
    main.app.dependency_overrides[get_current_active_user_html] = lambda: actor[0]
    monkeypatch.setattr(main, 'SessionLocal', factory)
    monkeypatch.setattr(template_context, 'SessionLocal', factory)
    template_context._CACHE._data.clear()
    yield {'db': db, 'client': TestClient(main.app), 'actor': actor, 'manager': admin, 'capo': capo,
           'outsider': outsider, 'site': site, 'other': other, 'person': person, 'machine': machine}
    main.app.dependency_overrides.clear()
    db.close()
    if combined is not None:
        combined.drop_all(engine)
    engine.dispose()


def report_payload(o):
    return {'date': '2026-09-16', 'site_id': o['site'].id, 'site_name_or_code': o['site'].name,
            'total_hours': 8, 'workers_count': 1, 'activities': 'Prova',
            'workers': [{'personale_id': o['person'].id, 'hours_worked': 8}]}


def test_draft_is_private_versioned_and_does_not_create_attendance(operations):
    o = operations; c = o['client']; db = o['db']
    assert c.get('/operazioni/bozza').json()['revision'] == 0
    saved = c.put('/operazioni/bozza', json={'revision': 0, 'payload': {'fields': {'attivita': 'Parziale'}}})
    assert saved.status_code == 200
    rev = saved.json()['revision']
    assert db.query(Report).count() == db.query(PersonalePresenza).count() == 0
    assert c.put('/operazioni/bozza', json={'revision': 0, 'payload': {}}).status_code == 409
    o['actor'][0] = o['outsider']
    assert c.get('/operazioni/bozza').json()['payload'] is None
    o['actor'][0] = o['capo']
    assert c.delete(f'/operazioni/bozza?revision={rev}').status_code == 200
    assert c.get('/operazioni/bozza').json()['payload'] is None
    assert c.put('/operazioni/bozza', json={'revision': rev, 'payload': {}}).status_code == 409


def test_draft_submission_is_atomic_and_retry_does_not_duplicate_report(operations):
    o = operations; c = o['client']; db = o['db']
    rev = c.put('/operazioni/bozza', json={'revision': 0, 'payload': {'fields': {'attivita': 'Prova'}}}).json()['revision']
    payload = {**report_payload(o), 'draft_revision': rev}
    first = c.post('/reports', json=payload)
    assert first.status_code == 201, first.text
    second = c.post('/reports', json=payload)
    assert second.status_code == 201
    assert first.json()['id'] == second.json()['id']
    assert db.query(Report).count() == 1
    assert db.query(PersonalePresenza).count() == 1
    assert c.get('/operazioni/bozza').json()['payload'] is None


def test_review_enforces_roles_stale_versions_and_approved_record_lock(operations):
    o = operations; c = o['client']
    report_id = c.post('/reports', json=report_payload(o)).json()['id']
    url = f'/operazioni/rapportini/{report_id}'
    assert c.get(url).status_code == 200
    assert c.post(url+'/stato', data={'version': 0, 'action': 'approved'}).status_code == 403
    o['actor'][0] = o['outsider']
    assert c.get(url).status_code == 403
    o['actor'][0] = o['manager']
    assert c.post(url+'/stato', data={'version': 0, 'action': 'approved'}, follow_redirects=False).status_code == 303
    assert c.put(f'/reports/{report_id}', json=report_payload(o)).status_code == 409
    assert c.delete(f'/reports/{report_id}').status_code == 409
    assert c.post(url+'/stato', data={'version': 0, 'action': 'changes_requested', 'note': 'Ore'}).status_code == 409
    assert c.post(url+'/stato', data={'version': 1, 'action': 'changes_requested', 'note': 'Verificare ore'}, follow_redirects=False).status_code == 303
    o['actor'][0] = o['capo']
    changed = {**report_payload(o), 'notes': 'Verificate', 'review_version': 2}
    assert c.put(f'/reports/{report_id}', json=changed).status_code == 200
    assert c.put(f'/reports/{report_id}', json=changed).status_code == 409
    assert c.post(url+'/stato', data={'version': 3, 'action': 'submitted'}, follow_redirects=False).status_code == 303


def test_daily_page_scopes_sites_and_links_existing_tasks(operations):
    o = operations; db = o['db']
    db.add_all([SiteTask(site_id=o['site'].id, title='Visibile', due_date=date(2026, 1, 1), created_by_id=o['manager'].id),
                SiteTask(site_id=o['other'].id, title='Segreto', due_date=date(2026, 1, 1), created_by_id=o['manager'].id)])
    db.commit()
    response = o['client'].get('/operazioni')
    assert response.status_code == 200, response.text
    assert 'Visibile' in response.text and 'Segreto' not in response.text
    assert o['other'].name not in response.text
    o['actor'][0] = o['manager']
    assert o['client'].get('/operazioni').status_code == 200


def test_weekly_planning_rejects_conflicts_and_preserves_attendance(operations):
    o = operations; c = o['client']; db = o['db']
    data = {'day': '2026-09-16', 'site_id': o['site'].id, 'resource': f"machine:{o['machine'].id}"}
    assert c.post('/operazioni/pianificazione', data=data).status_code == 403
    o['actor'][0] = o['manager']
    assert c.get('/operazioni/pianificazione?week=2026-09-16').status_code == 200
    assert c.post('/operazioni/pianificazione', data=data, follow_redirects=False).status_code == 303
    assert c.post('/operazioni/pianificazione', data={**data, 'site_id': o['other'].id}).status_code == 409
    assert db.query(ResourcePlan).count() == 1
    assert db.query(PersonalePresenza).count() == 0
    plan_id = db.query(ResourcePlan).one().id
    assert c.post(f'/operazioni/pianificazione/{plan_id}/elimina', follow_redirects=False).status_code == 303
    assert db.query(ResourcePlan).count() == 0


def test_document_revision_preserves_original_and_rejects_stale_upload(operations):
    o = operations; db = o['db']; c = o['client']
    doc = SiteDocument(site_id=o['site'].id, filename='plan.pdf', category=SiteDocumentCategoryEnum.documento,
                       data=b'original', size_bytes=8, uploaded_by_id=o['manager'].id)
    db.add(doc); db.commit()
    url = f'/operazioni/documenti/{doc.id}'
    assert c.get(url).status_code == 403
    o['actor'][0] = o['manager']
    assert c.get(url).status_code == 200
    upload = c.post(url+'/revisione', data={'current_id': doc.id, 'expires_on': '2027-01-01'},
                    files={'file': ('revision.pdf', b'revision', 'application/pdf')}, follow_redirects=False)
    assert upload.status_code == 303, upload.text
    version = db.query(DocumentVersion).one()
    assert version.number == 2 and version.root_id == doc.id
    assert db.get(SiteDocument, doc.id).data == b'original'
    assert db.get(SiteDocument, version.document_id).data == b'revision'
    assert c.get(url).status_code == 200
    assert c.post(url+'/revisione', data={'current_id': doc.id}, files={'file': ('old.pdf', b'old')}).status_code == 409
    assert c.post(f'/manager/documenti/{doc.id}/elimina').status_code == 409


@pytest.mark.parametrize('role', [RoleEnum.driver, RoleEnum.magazzino, RoleEnum.ferraiolo])
def test_operations_does_not_expand_roles(operations, role):
    o = operations
    o['capo'].role = role; o['db'].commit()
    for url in ['/operazioni', '/operazioni/bozza', '/operazioni/pianificazione']:
        assert o['client'].get(url).status_code == 403


def test_previous_report_is_author_scoped(operations):
    o = operations; c = o['client']
    c.post('/reports', json=report_payload(o))
    url = f"/operazioni/ultimo-rapportino?site_id={o['site'].id}&before=2026-09-17"
    assert c.get(url).status_code == 200
    o['actor'][0] = o['outsider']
    assert c.get(url).status_code == 403
    o['actor'][0] = o['manager']
    assert c.get(url).status_code == 404


@pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser checks opt-in')
def test_browser_restores_and_submits_draft_at_mobile_width(operations):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect

    o = operations; c = o['client']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def intercept(route):
            url = urlsplit(route.request.url)
            if url.netloc != 'testserver':
                route.abort(); return
            path = url.path + ('?' + url.query if url.query else '')
            response = c.request(route.request.method, path, content=route.request.post_data,
                                 headers={'Content-Type': route.request.headers.get('content-type', 'text/plain')})
            route.fulfill(status=response.status_code, body=response.content,
                          headers={k: v for k, v in response.headers.items() if k not in {'content-length', 'content-encoding'}})
        page.route('**/*', intercept)
        page.goto('http://testserver/capo/rapportini/nuovo')
        expect(page.locator('#draft-status')).to_contain_text('Le modifiche saranno salvate')
        page.locator('#data').fill('2026-09-16')
        page.locator('#cantiere_id').select_option(str(o['site'].id))
        page.locator('#attivita').fill('Attività da riprendere')
        expect(page.locator('#draft-status')).to_contain_text('Bozza salvata alle')
        page.reload()
        expect(page.locator('#draft-status')).to_contain_text('Bozza ripristinata')
        expect(page.locator('#attivita')).to_have_value('Attività da riprendere')
        assert o['db'].query(Report).count() == 0
        page.locator('#rapportino-form button[type=submit]').click()
        page.wait_for_url('**/capo/dashboard?rapportino_created=1')
        assert o['db'].query(Report).count() == 1
        assert o['db'].query(ReportDraft).one().payload == 'null'
        page.goto('http://testserver/operazioni')
        expect(page.get_by_role('heading', name='Rapportini da controllare')).to_be_visible()
        if os.getenv('OPERATIONS_SCREENSHOT'):
            page.screenshot(path=os.environ['OPERATIONS_SCREENSHOT'], full_page=True)
        assert not errors, errors
        browser.close()
