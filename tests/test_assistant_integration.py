"""Integration boundary and real business transactions, on an isolated database."""
import hashlib
import re
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import main
from auth import get_current_active_user_html
from models import AssistantProposal, AssistantRateBucket, Fiche, Report, PersonalePresenza, RoleEnum, TrasportoViaggio
from test_operations import operations

API = '/api/integrations/v1'
TOKEN = 'lenta_assistant_' + 'test-credential-' * 4


@pytest.fixture
def assistant(operations, monkeypatch):
    o = operations
    from database import ensure_model_columns
    from models import Base
    from sqlmodel import SQLModel
    ensure_model_columns(o['db'].get_bind(), (Base.metadata, SQLModel.metadata))
    o['db'].autoflush = False  # Match the production session factory.
    o['manager'].role = RoleEnum.admin
    o['db'].commit()
    o['actor'][0] = o['manager']
    for key, value in dict(ASSISTANT_API_ENABLED='true', ASSISTANT_OWNER_ID=str(o['manager'].id),
                           ASSISTANT_TOKEN_SHA256=hashlib.sha256(TOKEN.encode()).hexdigest(),
                           ASSISTANT_PUBLIC_ORIGIN='https://testserver',
                           ASSISTANT_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z').items():
        monkeypatch.setenv(key, value)
    o['headers'] = {'Authorization': 'Bearer ' + TOKEN}
    return o


def report(o):
    return dict(site_id=o['site'].id, date='2026-10-05', total_hours=8,
                workers=[dict(personale_id=o['person'].id, hours_worked=8)], activities='Scavo')


def propose(o, payload=None, kind='report.create', request_id=None):
    return o['client'].post(API+'/proposals', headers=o['headers'], json=dict(
        request_id=request_id or uuid4().hex, kind=kind, payload=payload if payload is not None else report(o)))


def approval(o, proposal, decision='approve', **kwargs):
    path = '/integrations/assistant/proposals/' + proposal['id']
    page = o['client'].get(path)
    assert page.status_code == 200, page.text
    token = re.search(r'name="csrf" value="([a-f0-9]+)"', page.text)[1]
    return o['client'].post(path, data=dict(csrf=token, decision=decision), **kwargs)


def test_disabled_and_incomplete_configuration_fail_closed(assistant, monkeypatch):
    o = assistant
    monkeypatch.setenv('ASSISTANT_API_ENABLED', 'false')
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 404
    monkeypatch.setenv('ASSISTANT_API_ENABLED', 'true')
    monkeypatch.delenv('ASSISTANT_OWNER_ID')
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 503


def test_cookie_and_normal_jwt_do_not_authorize_api(assistant):
    o = assistant
    for headers in ({}, {'Authorization': 'Bearer not-valid'}, {'Authorization': 'Basic '+TOKEN}):
        assert o['client'].get(API+'/sites', headers=headers).status_code == 401
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 200


@pytest.mark.parametrize('change', ['inactive', 'role', 'owner'])
def test_access_revoked_when_owner_changes(assistant, monkeypatch, change):
    o = assistant
    if change == 'inactive':
        o['manager'].is_active = False
    elif change == 'role':
        o['manager'].role = RoleEnum.manager
    else:
        monkeypatch.setenv('ASSISTANT_OWNER_ID', str(o['outsider'].id))
    o['db'].commit()
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 403


def test_read_contracts_pagination_and_private_headers(assistant):
    o = assistant; c = o['client']
    paths = ['/capabilities', '/openapi.json', '/sites?limit=1', '/sites/'+str(o['site'].id),
             f'/sites/{o["site"].id}/progress', f'/sites/{o["site"].id}/fiche-context?numero_pannello=1',
             '/personnel', '/attendance', '/hours?from_date=2026-10-01&to_date=2026-10-31', '/reports', '/fiches', '/trips']
    paths += ['/catalog/'+collection for collection in ['assets', 'places', 'drivers', 'vehicles', 'machines', 'site_managers']]
    for path in paths:
        response = c.get(API+path, headers=o['headers'])
        assert response.status_code == 200, (path, response.text)
        assert response.headers['cache-control'] == 'no-store'
        assert 'hashed_password' not in response.text and 'access_token' not in response.text
    assert c.get(API+'/sites?limit=1', headers=o['headers']).json()['next_offset'] == 1
    assert c.get(API+'/sites?limit=201', headers=o['headers']).status_code == 422
    assert c.get(API+'/attendance?from_date=2026-12-01&to_date=2026-01-01', headers=o['headers']).status_code == 422
    assert c.get(API+'/hours?from_date=2020-01-01&to_date=2026-01-01', headers=o['headers']).status_code == 422
    schema = c.get(API+'/openapi.json', headers=o['headers']).json()
    assert len(schema['components']['schemas']['ProposalInput']['oneOf']) == 3
    assert 'hours_worked' in schema['components']['schemas']['WorkerInput']['required']
    assert schema['security'] == [{'AssistantBearer': []}]


def test_report_preview_has_no_business_effect_then_approval_saves_once(assistant):
    o = assistant; db = o['db']; c = o['client']
    response = propose(o)
    assert response.status_code == 201, response.text
    p = response.json()
    assert p['approval_url'].startswith('https://testserver/')
    assert db.query(Report).count() == db.query(PersonalePresenza).count() == 0
    response = approval(o, p)
    assert response.status_code == 200, response.text
    assert db.query(Report).count() == db.query(PersonalePresenza).count() == 1
    status = c.get(API+'/proposals/'+p['id'], headers=o['headers']).json()
    assert status['state'] == 'applied'
    from services.assistant_security import csrf_token
    row = db.get(AssistantProposal, p['id'])
    response = c.post('/integrations/assistant/proposals/'+p['id'], data=dict(decision='approve', csrf=csrf_token(row)))
    assert response.status_code == 200
    assert db.query(Report).count() == 1
    for path in ['/reports', '/reports/'+str(status['result']['id']), '/attendance', '/hours?from_date=2026-10-05&to_date=2026-10-05']:
        response = c.get(API+path, headers=o['headers'])
        assert response.status_code == 200, response.text
    assert propose(o).status_code == 409  # Never overwrite existing attendance.


def test_idempotency_and_payload_conflict(assistant):
    o = assistant; key = uuid4().hex
    first = propose(o, request_id=key)
    assert first.status_code == 201, first.text
    second = propose(o, request_id=key)
    assert second.json()['id'] == first.json()['id']
    assert propose(o, {**report(o), 'total_hours': 9}, request_id=key).status_code == 409
    assert o['db'].query(AssistantProposal).count() == 1


def test_rejection_never_saves(assistant):
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    assert approval(o, response.json(), 'reject').status_code == 200
    assert o['db'].query(Report).count() == 0
    assert o['db'].query(AssistantProposal).one().state == 'rejected'


@pytest.mark.parametrize('headers', [{'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'Authorization': 'Bearer '+TOKEN}])
def test_approval_rejects_cross_site_and_api_channel(assistant, headers):
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    assert approval(o, response.json(), headers=headers).status_code == 403
    assert o['db'].query(Report).count() == 0


def test_approval_requires_owner_session_and_csrf(assistant):
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    path = '/integrations/assistant/proposals/'+response.json()['id']
    assert o['client'].post(path, data=dict(decision='approve', csrf='bad')).status_code == 403
    o['outsider'].role = RoleEnum.admin; o['db'].commit(); o['actor'][0] = o['outsider']
    assert o['client'].get(path).status_code == 403
    main.app.dependency_overrides.pop(get_current_active_user_html)
    assert o['client'].get(path, headers=o['headers'], follow_redirects=False).status_code in (303, 307, 401)
    assert o['db'].query(Report).count() == 0


def test_expiry_rotation_and_changed_business_data(assistant, monkeypatch):
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    p = response.json(); row = o['db'].get(AssistantProposal, p['id'])
    row.expires_at = datetime.utcnow()-timedelta(seconds=1); o['db'].commit()
    from services.assistant_security import csrf_token
    path = '/integrations/assistant/proposals/'+p['id']
    assert o['client'].post(path, data=dict(decision='approve', csrf=csrf_token(row))).status_code == 410
    row.expires_at = datetime.utcnow()+timedelta(minutes=20); o['db'].commit()
    o['site'].name = 'Nome cambiato'; o['db'].commit()
    assert approval(o, p).status_code == 409
    assert o['db'].query(Report).count() == 0
    assert o['db'].get(AssistantProposal, p['id']).state == 'pending'
    monkeypatch.setenv('ASSISTANT_TOKEN_SHA256', '0'*64)
    assert o['client'].get(path).status_code == 404
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 401


def test_atomic_rollback_when_audit_fails(assistant, monkeypatch):
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    import services.assistant_operations as service
    def fail(*args, **kwargs):
        raise RuntimeError('simulated audit failure')
    monkeypatch.setattr(service, 'log_audit_event', fail)
    with pytest.raises(RuntimeError, match='simulated audit failure'):
        approval(o, response.json())
    assert o['db'].query(Report).count() == o['db'].query(PersonalePresenza).count() == 0
    assert o['db'].query(AssistantProposal).one().state == 'pending'


def test_validation_does_not_accept_extra_fields_or_missing_hours(assistant):
    o = assistant
    assert propose(o, {**report(o), 'confirmed': True}).status_code == 422
    payload = report(o); del payload['workers'][0]['hours_worked']
    assert propose(o, payload).status_code == 422
    assert propose(o, {**report(o), 'site_id': 999999}).status_code == 409
    assert o['db'].query(Report).count() == o['db'].query(AssistantProposal).count() == 0


def test_request_limits(assistant):
    import time
    o = assistant
    o['db'].add(AssistantRateBucket(key=f'{o["manager"].id}:read:{int(time.time()//60)}', window=int(time.time()//60), count=120))
    o['db'].commit()
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 429
    assert o['client'].post(API+'/proposals', headers=o['headers'], content=b'x'*131073).status_code == 413


def test_fiche_preview_approval_and_detail(assistant):
    from test_site_pours import setup
    o = assistant; setup(o)
    payload = dict(cantiere_id=o['site'].id, numero_pannello=1, data_scavo='2026-10-05', operatore='Squadra',
        tipologia_scavo='paratia', profondita_totale=10, strato_da=[0], strato_a=[10], strato_materiale=['sabbia'])
    response = propose(o, payload, 'fiche.create')
    assert response.status_code == 201, response.text
    assert o['db'].query(Fiche).count() == 0
    response = approval(o, response.json())
    assert response.status_code == 200, response.text
    fiche = o['db'].query(Fiche).one()
    assert fiche.larghezza_pannello == 5
    response = o['client'].get(API+'/fiches/'+str(fiche.id), headers=o['headers'])
    assert response.status_code == 200, response.text
    assert len(response.json()['stratigrafie']) == 1


def test_trip_preview_approval_preserves_asset_locations(assistant):
    from test_fleet import setup
    o = assistant; payload, driver, pump, gen, bucket = setup(o)
    payload.pop('token')
    for move in payload['moves']:
        move.setdefault('reason', 'Trasferimento')
    response = propose(o, payload, 'trip.create')
    assert response.status_code == 201, response.text
    assert o['db'].query(TrasportoViaggio).count() == 0
    response = approval(o, response.json())
    assert response.status_code == 200, response.text
    trip = o['db'].query(TrasportoViaggio).one()
    assert pump.posizione_attuale == 'Deposito'
    for path in ['/trips', '/trips/'+str(trip.id)]:
        response = o['client'].get(API+path, headers=o['headers'])
        assert response.status_code == 200, response.text


def test_real_browser_session_confirms_but_cannot_replace_api_credential(assistant):
    from auth import create_access_token
    o = assistant; response = propose(o); assert response.status_code == 201, response.text
    main.app.dependency_overrides.pop(get_current_active_user_html)
    jwt = create_access_token(dict(sub=o['manager'].email, role='admin'))
    o['client'].cookies.set('access_token', jwt)
    assert o['client'].get(API+'/sites').status_code == 401
    assert o['client'].get(API+'/sites', headers={'Authorization': 'Bearer '+jwt}).status_code == 401
    assert approval(o, response.json()).status_code == 200
    assert o['db'].query(Report).count() == 1


@pytest.mark.parametrize('expiry', ['2020-01-01T00:00:00Z', '2099-01-01', 'invalid'])
def test_credential_expiry_is_required_and_enforced(assistant, monkeypatch, expiry):
    o = assistant
    monkeypatch.setenv('ASSISTANT_TOKEN_EXPIRES_AT', expiry)
    assert o['client'].get(API+'/sites', headers=o['headers']).status_code == 503


def test_review_escapes_untrusted_text_and_uses_configured_origin(assistant):
    o = assistant; payload = report(o); payload['notes'] = '<script>alert(1)</script>'
    response = o['client'].post(API+'/proposals', headers={**o['headers'], 'Host': 'evil.example'},
        json=dict(request_id=uuid4().hex, kind='report.create', payload=payload))
    assert response.status_code == 201, response.text
    assert response.json()['approval_url'].startswith('https://testserver/')
    page = o['client'].get('/integrations/assistant/proposals/'+response.json()['id'])
    assert '<script>alert(1)</script>' not in page.text
    assert '&lt;script&gt;' in page.text
    assert page.headers['x-frame-options'] == 'DENY'


def test_second_pending_proposal_cannot_overwrite_approved_attendance(assistant):
    from models import Notification, AuditLog
    o = assistant
    first, second = propose(o), propose(o)
    assert first.status_code == second.status_code == 201
    assert o['db'].query(Notification).count() == 0
    assert approval(o, first.json()).status_code == 200
    assert approval(o, second.json()).status_code == 409
    assert o['db'].query(Report).count() == o['db'].query(PersonalePresenza).count() == 1
    events = o['db'].query(AuditLog).filter_by(action='assistant.applied').all()
    assert len(events) == 1 and events[0].target_id == o['db'].query(Report).one().id
    assert TOKEN not in str([e.extra_data for e in o['db'].query(AuditLog)])


def test_fiche_rejects_project_change_since_preview(assistant):
    from test_site_pours import setup
    from models import SiteCoupe
    o = assistant; setup(o)
    payload = dict(cantiere_id=o['site'].id, numero_pannello=1, data_scavo='2026-10-05', operatore='Squadra',
        tipologia_scavo='paratia', profondita_totale=10, strato_da=[0], strato_a=[10], strato_materiale=['sabbia'])
    response = propose(o, payload, 'fiche.create')
    assert response.status_code == 201, response.text
    coupe = o['db'].query(SiteCoupe).one(); coupe.spessore = .6; o['db'].commit()
    assert approval(o, response.json()).status_code == 409
    assert o['db'].query(Fiche).count() == 0


def test_chunked_requests_are_bounded(assistant):
    o = assistant
    def body():
        for _ in range(130):
            yield b'x'*1024
    response = o['client'].post(API+'/proposals', headers=o['headers'], content=body())
    assert response.status_code == 413
