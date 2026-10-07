"""OAuth and MCP integration tests against isolated SQLite/PostgreSQL databases."""
import base64
from datetime import datetime, timedelta
import hashlib
import os
import re
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import pytest
import main
from auth import create_access_token, get_current_active_user_html
from models import AssistantOAuthCode, AssistantOAuthGrant, AssistantOAuthToken, Fiche
from services.assistant_oauth import ROOT, MCP, SCOPES, RESUME_COOKIE, resource
from test_assistant_integration import assistant, API, report
from test_operations import operations
from test_site_pours import setup

CALLBACK = 'https://chatgpt.com/connector_platform_oauth_redirect'
VERIFIER = 'a' * 64


@pytest.fixture
def connected(assistant):
    o = assistant
    main.app.dependency_overrides.pop(get_current_active_user_html, None)
    o['client'].cookies.set('access_token', 'Bearer ' + create_access_token({'sub': o['manager'].email, 'role': 'admin'}))
    return o


def registration(o):
    r = o['client'].post(ROOT + '/register', json={'redirect_uris': [CALLBACK],
        'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token']})
    assert r.status_code == 201, r.text
    return r.json()['client_id']


def params(o, scopes=SCOPES, **overrides):
    return dict(client_id=registration(o), redirect_uri=CALLBACK, response_type='code',
        state='opaque-chatgpt-state', resource=resource(), scope=' '.join(scopes),
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip('='),
        code_challenge_method='S256', **overrides)


def consent_form(o, p):
    r = o['client'].get(ROOT + '/authorize', params=p, follow_redirects=False)
    assert r.status_code == 200, r.text
    return {name: re.search(r'name="' + name + r'" value="([a-f0-9]+)"', r.text)[1] for name in ('flow_id', 'csrf')}


def authorization(o, scopes=SCOPES):
    p = params(o, scopes)
    form = consent_form(o, p)
    r = o['client'].post(ROOT + '/authorize', data={**form, 'decision': 'allow'}, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlsplit(r.headers['location']).query)
    assert q['iss'] == ['https://testserver'] and q['state'] == [p['state']]
    return p, q['code'][0]


def exchange(o, p, code, **overrides):
    body = dict(grant_type='authorization_code', client_id=p['client_id'], redirect_uri=CALLBACK,
                code=code, code_verifier=VERIFIER, resource=resource())
    return o['client'].post(ROOT + '/token', data={**body, **overrides})


def connect(o, scopes=SCOPES):
    p, code = authorization(o, scopes)
    r = exchange(o, p, code)
    assert r.status_code == 200, r.text
    return p, r.json()


def call(o, token, name, arguments=None):
    return o['client'].post(MCP, headers={'Authorization': 'Bearer ' + token} if token else {},
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
              'params': {'name': name, 'arguments': arguments or {}}})


def test_discovery_handshake_catalog_and_closed_data(connected):
    o = connected; c = o['client']
    metadata = c.get('/.well-known/oauth-protected-resource' + MCP)
    assert metadata.json()['resource'] == resource()
    issuer = c.get('/.well-known/oauth-authorization-server').json()
    assert issuer['code_challenge_methods_supported'] == ['S256']
    assert issuer['authorization_response_iss_parameter_supported'] is True
    for method in ('initialize', 'tools/list', 'ping'):
        r = c.post(MCP, json={'jsonrpc': '2.0', 'id': 1, 'method': method})
        assert r.status_code == 200, r.text
        assert r.headers['cache-control'] == 'no-store'
    tools = c.post(MCP, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()['result']['tools']
    assert len(tools) == 20
    assert all(t['securitySchemes'][0]['type'] == 'oauth2' for t in tools)
    assert not any('confirm' in t['name'] or 'delete' in t['name'] for t in tools)
    assert call(o, None, 'lenta_sites').status_code == 401
    assert c.get(MCP).status_code == 401
    p, tokens = connect(o)
    r = call(o, tokens['access_token'], 'lenta_sites')
    assert r.json()['result']['structuredContent']['items'][0]['id'] == o['site'].id
    assert call(o, tokens['access_token'], 'lenta_sites', {'limit': 9999}).json()['result']['isError']
    assert c.get(API + '/sites', headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code == 401
    assert c.get(MCP, headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code == 405
    row = o['db'].query(AssistantOAuthToken).one()
    assert tokens['access_token'] not in str(row.__dict__) and tokens['refresh_token'] not in str(row.__dict__)


def test_owner_consent_csrf_denial_and_login_resume(connected):
    o = connected; c = o['client']; p = params(o)
    c.cookies.clear()
    r = c.get(ROOT + '/authorize', params=p, follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/login'
    assert RESUME_COOKIE in r.headers['set-cookie']
    from services.assistant_oauth import resume_path
    from starlette.requests import Request
    cookie = r.cookies.get(RESUME_COOKIE)
    req = Request({'type': 'http', 'headers': [(b'cookie', (RESUME_COOKIE + '=' + cookie).encode())]})
    assert resume_path(req).startswith(ROOT + '/authorize?flow=')
    c.cookies.set('access_token', 'Bearer ' + create_access_token({'sub': o['capo'].email, 'role': 'caposquadra'}))
    assert c.get(ROOT + '/authorize', params=p).status_code == 403
    c.cookies.set('access_token', 'Bearer ' + create_access_token({'sub': o['manager'].email, 'role': 'admin'}))
    form = consent_form(o, p)
    assert c.post(ROOT + '/authorize', data={**form, 'decision': 'allow', 'csrf': 'bad'}).status_code == 403
    assert c.post(ROOT + '/authorize', data={**form, 'decision': 'allow'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    denied = c.post(ROOT + '/authorize', data={**form, 'decision': 'deny'}, follow_redirects=False)
    assert 'error=access_denied' in denied.headers['location']
    assert o['db'].query(AssistantOAuthCode).count() == 0
    assert c.post(ROOT + '/authorize', data={**form, 'decision': 'allow'}).status_code == 410


@pytest.mark.parametrize('callback', ['https://evil.example/cb', 'https://chatgpt.com.evil.example/cb',
    'https://chatgpt.com/connector_platform_oauth_redirect?next=evil', 'http://chatgpt.com/connector_platform_oauth_redirect'])
def test_registration_rejects_untrusted_callbacks(connected, callback):
    assert connected['client'].post(ROOT + '/register', json={'redirect_uris': [callback]}).status_code == 400


def test_pkce_resource_redirect_expiry_and_single_use(connected):
    o = connected; c = o['client']; p = params(o)
    for change in ({'code_challenge_method': 'plain'}, {'resource': 'https://evil.example'}, {'scope': 'admin'}, {'redirect_uri': 'https://evil.example'}):
        assert c.get(ROOT + '/authorize', params={**p, **change}).status_code == 400
    p, code = authorization(o)
    assert exchange(o, p, code, code_verifier='b' * 64).status_code == 400
    assert exchange(o, p, code, resource='https://evil.example').status_code == 400
    assert exchange(o, p, code, redirect_uri='https://evil.example').status_code == 400
    good = exchange(o, p, code)
    assert good.status_code == 200, good.text
    assert exchange(o, p, code).status_code == 400
    assert call(o, good.json()['access_token'], 'lenta_sites').status_code == 401
    p, code = authorization(o)
    row = o['db'].query(AssistantOAuthCode).filter_by(consumed=False).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1); o['db'].commit()
    assert exchange(o, p, code).status_code == 400


def test_refresh_rotation_scope_and_revocation(connected):
    o = connected; c = o['client']; p, tokens = connect(o, ['lenta.read'])
    assert call(o, tokens['access_token'], 'lenta_prepare_report', {'request_id': uuid4().hex, 'payload': report(o)}).status_code == 403
    body = {'grant_type': 'refresh_token', 'client_id': p['client_id'], 'resource': resource(), 'refresh_token': tokens['refresh_token']}
    assert c.post(ROOT + '/token', data={**body, 'scope': 'lenta.read lenta.prepare'}).status_code == 400
    renewed = c.post(ROOT + '/token', data=body)
    assert renewed.status_code == 200, renewed.text
    assert call(o, tokens['access_token'], 'lenta_sites').status_code == 401
    assert call(o, renewed.json()['access_token'], 'lenta_sites').status_code == 200
    assert c.post(ROOT + '/token', data=body).status_code == 400
    assert call(o, renewed.json()['access_token'], 'lenta_sites').status_code == 401
    p, tokens = connect(o)
    page = c.get('/integrations/assistant/connections')
    csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', page.text)[1]
    assert c.post('/integrations/assistant/connections/revoke', data={'csrf': csrf}, follow_redirects=False).status_code == 303
    assert call(o, tokens['access_token'], 'lenta_sites').status_code == 401


@pytest.mark.parametrize('change', ['inactive', 'owner', 'key', 'expired'])
def test_owner_and_configuration_changes_revoke_connection(connected, monkeypatch, change):
    o = connected; p, tokens = connect(o)
    if change == 'inactive':
        o['manager'].is_active = False; o['db'].commit()
    elif change == 'owner':
        monkeypatch.setenv('ASSISTANT_OWNER_ID', str(o['capo'].id))
    elif change == 'key':
        monkeypatch.setenv('ASSISTANT_TOKEN_SHA256', 'a' * 64)
    else:
        o['db'].query(AssistantOAuthGrant).one().expires_at = datetime.utcnow() - timedelta(seconds=1); o['db'].commit()
    assert call(o, tokens['access_token'], 'lenta_sites').status_code == 401


def test_mcp_fiche_roundtrip_pending_and_idempotent(connected):
    o = connected; setup(o); p, tokens = connect(o); access = tokens['access_token']
    values = {'request_id': uuid4().hex, 'payload': dict(cantiere_id=o['site'].id, numero_pannello=1,
        data_scavo='2026-10-07', operatore='Squadra', tipologia_scavo='paratia', profondita_totale=10,
        strato_da=[0], strato_a=[10], strato_materiale=['sabbia'])}
    r = call(o, access, 'lenta_prepare_fiche', values)
    assert not r.json()['result']['isError'], r.text
    proposal = r.json()['result']['structuredContent']
    assert o['db'].query(Fiche).count() == 0
    r = call(o, access, 'lenta_submit_fiche', {'proposal_id': proposal['id']})
    assert not r.json()['result']['isError'], r.text
    again = call(o, access, 'lenta_submit_fiche', {'proposal_id': proposal['id']})
    assert again.json()['result']['structuredContent'] == r.json()['result']['structuredContent']
    assert o['db'].query(Fiche).one().review_status == 'pending'
    o['db'].refresh(o['site']); assert o['site'].paratie_done_panels == 0


def test_malformed_protocol_and_boundary(connected):
    c = connected['client']
    for body in ([], {'jsonrpc': '2.0', 'id': True, 'method': 'ping'}, {'jsonrpc': '1.0', 'method': 'ping'}):
        assert c.post(MCP, json=body).json()['error']['code'] == -32600
    assert c.post(MCP, content='{' * 131073, headers={'Content-Type': 'application/json'}).status_code == 413
    assert c.post(MCP, json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert c.post(ROOT + '/register', json={'redirect_uris': [CALLBACK], 'grant_types': [{}]}).status_code == 400


def test_real_login_resumes_owner_consent(connected):
    from fastapi.testclient import TestClient
    from auth import hash_password
    o = connected
    o['manager'].hashed_password = hash_password('Disposable-OAuth-test-2026')
    o['db'].commit()
    c = TestClient(main.app, base_url='https://testserver')
    p = params(o)
    start = c.get(ROOT + '/authorize', params=p, follow_redirects=False)
    assert start.status_code == 303 and start.headers['location'] == '/login'
    login = c.post('/login', data={'email': o['manager'].email, 'password': 'Disposable-OAuth-test-2026'}, follow_redirects=False)
    assert login.status_code == 303, login.text
    assert login.headers['location'].startswith(ROOT + '/authorize?flow=')
    page = c.get(login.headers['location'])
    assert page.status_code == 200 and 'Autorizza ChatGPT' in page.text
    assert RESUME_COOKIE not in c.cookies


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='Requires real PostgreSQL row locks')
def test_concurrent_code_exchange_issues_only_one_token(connected):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from database import get_db
    o = connected; p, code = authorization(o)
    factory = sessionmaker(bind=o['db'].get_bind(), autoflush=False)
    previous = main.app.dependency_overrides[get_db]
    def database_session():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = database_session
    try:
        def run():
            c = TestClient(main.app)
            return c.post(ROOT + '/token', data={'grant_type': 'authorization_code',
                'client_id': p['client_id'], 'code': code, 'code_verifier': VERIFIER,
                'redirect_uri': CALLBACK, 'resource': resource()}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run) for _ in range(2)]
            assert sorted(job.result(timeout=20) for job in jobs) == [200, 400]
        o['db'].expire_all()
        assert o['db'].query(AssistantOAuthToken).count() == 1
    finally:
        main.app.dependency_overrides[get_db] = previous
