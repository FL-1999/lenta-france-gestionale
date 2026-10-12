import json
import os
from datetime import datetime, timedelta, date
from uuid import uuid4
import pytest
from models import AssistantProposal, Site, AuditLog, SiteStatusEnum
from test_operations import operations
from test_assistant_integration import assistant, propose, approval, API
from test_assistant_mcp import connected, connect, call
from test_site_works import setup, layout


def patch(o, changes, kind='site.progress.update', **extra):
    return propose(o, {'site_id': o['site'].id, 'changes': changes, **extra}, kind)


def apply(o, proposal):
    return o['client'].post(API + '/proposals/' + proposal['id'] + '/apply-site-update', headers=o['headers'])


def test_increment_preview_apply_idempotency_and_shared_progress(assistant):
    o = assistant; db = o['db']; site = o['site']
    site.cordoli_total_m = 100; site.cordoli_done_m = 20; site.installazione_cantiere_pct = 35; db.commit()
    response = patch(o, {'cordoli_increment_m': 12})
    assert response.status_code == 201, response.text
    p = response.json(); db.refresh(site)
    assert site.cordoli_done_m == 20
    assert p['summary']['Modifiche'][0]['prima'] == 20
    assert p['summary']['Modifiche'][0]['dopo'] == 32
    result = apply(o, p); assert result.status_code == 200, result.text
    assert apply(o, p).json()['result'] == result.json()['result']
    db.refresh(site); assert site.cordoli_done_m == 32 and site.installazione_cantiere_pct == 35
    progress = o['client'].get(f'/manager/cantieri/{site.id}/avanzamento/data').json()
    assert progress['summary']['cordoli']['done'] == 32
    assert progress['summary']['cordoli']['percent'] == 32
    assert db.query(AuditLog).filter_by(action='ASSISTANT_SITE_PATCH').count() == 1


def test_automatic_total_and_plan_change_invalidate_preview(assistant):
    o = assistant; db = o['db']; site = o['site']; setup(o)
    p = patch(o, {'cordoli_done_m': 8}).json()
    assert p['summary']['Dopo']['configuration']['guide_auto']
    assert p['summary']['Dopo']['configuration']['guide_total_m'] == 32
    plan = site.plans[0]; new = layout(); new['panels'][0]['width_m'] = 20
    plan.approved = json.dumps(new); plan.approved_revision += 1; db.commit()
    assert apply(o, p).status_code == 409
    db.refresh(site); assert not site.cordoli_done_m and site.cordoli_total_m is None
    p = patch(o, {'cordoli_done_m': 9}).json()
    assert apply(o, p).status_code == 200
    db.refresh(site); assert site.cordoli_total_m is None and site.cordoli_done_m == 9


def test_concurrent_previews_do_not_overwrite_or_double_add(assistant):
    o = assistant; site = o['site']; site.cordoli_total_m = 100; site.cordoli_done_m = 10; o['db'].commit()
    first = patch(o, {'cordoli_increment_m': 5}).json()
    second = patch(o, {'cordoli_increment_m': 7}).json()
    assert apply(o, first).status_code == 200
    assert apply(o, second).status_code == 409
    o['db'].refresh(site); assert site.cordoli_done_m == 15
    assert o['db'].get(AssistantProposal, second['id']).state == 'pending'


@pytest.mark.parametrize('changes', [{}, {'cordoli_done_m': -1}, {'cordoli_total_m': 0},
    {'cordoli_increment_m': 2, 'cordoli_done_m': 2}, {'cordoli_increment_m': None},
    {'installazione_cantiere_pct': 101}, {'paratie_done_panels': 10}, {'cordoli_done_m': None}])
def test_invalid_or_derived_progress_rejected(assistant, changes):
    assert patch(assistant, changes).status_code == 422


def test_totals_and_map_sources_cannot_be_bypassed(assistant):
    o = assistant; db = o['db']; site = o['site']
    assert patch(o, {'cordoli_done_m': 2}).status_code == 422
    assert patch(o, {'cordoli_total_m': 1, 'cordoli_done_m': 2}).status_code == 422
    c, url, body = setup(o); assert c.put(url + '/data', json=body).status_code == 200
    for field in ('rabotage_pct', 'pozzi_pompaggio_pct'):
        assert patch(o, {field: 50}).status_code == 400
    db.refresh(site); assert not site.cordoli_done_m


def test_details_patch_preserves_omitted_and_clears_explicit_null(assistant):
    o = assistant; db = o['db']; site = o['site']
    site.code = 'TEST'; site.projet_client = 'Cliente'; site.projet_indice = 'A'; site.start_date = date(2026, 1, 1); db.commit()
    p = patch(o, {'projet_indice': None, 'end_date': '2026-12-31', 'name': 'Nome aggiornato'}, 'site.details.update').json()
    db.refresh(site); assert site.name != 'Nome aggiornato' and site.projet_indice == 'A'
    assert apply(o, p).status_code == 200
    db.refresh(site)
    assert site.name == 'Nome aggiornato' and site.projet_indice is None
    assert site.projet_client == 'Cliente' and site.code == 'TEST' and site.start_date == date(2026, 1, 1)
    assert site.end_date == date(2026, 12, 31)


def test_details_dates_code_responsible_and_location_validation(assistant):
    o = assistant; db = o['db']; site = o['site']
    site.start_date = date(2026, 5, 1); site.address = 'Vecchia via'; site.lat = 48; site.lng = 2; site.place_id = 'old'
    o['other'].code = 'TAKEN'; db.commit()
    for changes, status in [({'end_date': '2026-04-01'}, 422), ({'code': 'TAKEN'}, 409),
        ({'name': '   '}, 422), ({'caposquadra_id': o['manager'].id}, 422), ({'lat': 20}, 422),
        ({'is_active': False}, 422), ({'address': 'Nuova via'}, 422)]:
        assert patch(o, changes, 'site.details.update').status_code == status
    p = patch(o, {'address': 'Nuova via'}, 'site.details.update', confirm_unverified_address=True).json()
    assert any(x['campo'] == 'lat' and x['dopo'] is None for x in p['summary']['Modifiche'])
    assert apply(o, p).status_code == 200
    db.refresh(site); assert site.address == 'Nuova via' and site.lat is None and site.lng is None and site.place_id is None


def test_scoped_oauth_owner_and_operation_boundaries(connected):
    o = connected
    _, old = connect(o, ['lenta.read', 'lenta.prepare', 'lenta.fiches.submit'])
    result = call(o, old['access_token'], 'lenta_prepare_site_progress_update',
        {'request_id': uuid4().hex, 'payload': {'site_id': o['site'].id, 'changes': {'installazione_cantiere_pct': 30}}})
    assert not result.json()['result']['isError'], result.text
    p = result.json()['result']['structuredContent']
    denied = call(o, old['access_token'], 'lenta_apply_site_update', {'proposal_id': p['id']})
    assert denied.status_code == 403 and 'lenta.sites.update' in denied.headers['www-authenticate']
    assert call(o, old['access_token'], 'lenta_submit_fiche', {'proposal_id': p['id']}).json()['result']['isError']
    _, new = connect(o, ['lenta.read', 'lenta.prepare', 'lenta.sites.update'])
    saved = call(o, new['access_token'], 'lenta_apply_site_update', {'proposal_id': p['id']})
    assert not saved.json()['result']['isError'], saved.text
    o['db'].refresh(o['site']); assert o['site'].installazione_cantiere_pct == 30
    assert apply(o, propose(o).json()).status_code == 403


def test_expired_rejected_closed_and_changed_details_fail_without_writes(assistant):
    o = assistant; db = o['db']; site = o['site']
    p = patch(o, {'installazione_cantiere_pct': 30}).json()
    row = db.get(AssistantProposal, p['id']); row.expires_at = datetime.utcnow() - timedelta(minutes=1); db.commit()
    assert apply(o, p).status_code == 410
    p = patch(o, {'installazione_cantiere_pct': 30}).json()
    assert approval(o, p, 'reject').status_code == 200
    assert apply(o, p).status_code == 409
    p = patch(o, {'name': 'Nuovo nome'}, 'site.details.update').json()
    site.projet_client = 'Modificato nel gestionale'; db.commit()
    assert apply(o, p).status_code == 409
    db.refresh(site); assert site.name != 'Nuovo nome' and site.projet_client == 'Modificato nel gestionale'
    site.status = SiteStatusEnum.chiuso; db.commit()
    assert patch(o, {'installazione_cantiere_pct': 30}).status_code == 409


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='Requires real PostgreSQL row locks')
def test_parallel_increments_keep_only_confirmed_preview(assistant):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from database import get_db
    import main
    o = assistant; site = o['site']; site.cordoli_total_m = 100; site.cordoli_done_m = 10; o['db'].commit()
    proposals = [patch(o, {'cordoli_increment_m': increment}).json() for increment in (5, 7)]
    factory = sessionmaker(bind=o['db'].get_bind(), autoflush=False)
    previous = main.app.dependency_overrides[get_db]
    def database_session():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = database_session
    barrier = Barrier(2)
    try:
        def run(proposal):
            client = TestClient(main.app)
            try:
                barrier.wait(timeout=10)
                return client.post(API + '/proposals/' + proposal['id'] + '/apply-site-update', headers=o['headers']).status_code
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run, proposal) for proposal in proposals]
            assert sorted(job.result(timeout=30) for job in jobs) == [200, 409]
        o['db'].expire_all()
        assert o['db'].get(Site, site.id).cordoli_done_m in (15, 17)
        assert o['db'].query(AuditLog).filter_by(action='ASSISTANT_SITE_PATCH').count() == 1
    finally:
        main.app.dependency_overrides[get_db] = previous
