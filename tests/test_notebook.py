"""Privacy boundaries and real persistence; no production AI calls."""
import json
from datetime import datetime
from uuid import uuid4
import httpx
import pytest
from fastapi import HTTPException
from models import (NotebookNote, NotebookGrant, NotebookRevision, NotebookDraft, NotebookAIQuota,
                    Notification, AuditLog, RoleEnum, ResourcePlan, Report, SiteTask)
from routes.notebook import token
from services import notebook as svc, notebook_ai as ai
from test_operations import operations
from test_personnel_workspace import personnel


def call(o, method, path='', body=None, actor=None, **kwargs):
    if actor is not None:
        o['actor'][0] = actor
    return o['client'].request(method, '/appunti'+path, json=body,
        headers={'X-CSRF-Token': token(o['actor'][0])}, **kwargs)


def create(o, **extra):
    r = call(o, 'POST', body=dict(title='Appunto riservato', body='P5, 6.3 m. Verificare con il capo.',
        request_key=uuid4().hex, **extra))
    assert r.status_code == 200, r.text
    return r.json()


def edit(o, n, **extra):
    body = {k: n[k] for k in ('title', 'body', 'kind', 'details', 'version', 'site_id', 'collection')}
    return call(o, 'PUT', f"/{n['id']}", {**body, **extra})


def sharing(o, n, grants):
    return call(o, 'PUT', f"/{n['id']}/condivisione", dict(version=n['version'], grants=grants, confirm=True))


def test_private_even_for_admin_and_same_site_no_search_or_history_leaks(operations):
    o = operations
    n = create(o, site_id=o['site'].id, collection='Raccolta segreta')
    assert n['owner'] and not n['shared'] and n['can_edit']
    for role in (RoleEnum.manager, RoleEnum.admin):
        o['manager'].role = role
        o['db'].commit()
        o['actor'][0] = o['manager']
        assert call(o, 'GET', f"/{n['id']}").status_code == 404
        for suffix in ('originali', 'destinatari'):
            assert call(o, 'GET', f"/{n['id']}/{suffix}").status_code == 404
        for scope in ('mine', 'received', 'all', 'archived'):
            r = call(o, 'GET', f"/data?scope={scope}&site_id={o['site'].id}")
            assert r.status_code == 200 and r.json()['notes'] == []
            assert 'segreta' not in r.text
        assert edit(o, n, body='Rubato').status_code == 404
        assert sharing(o, n, []).status_code == 404
    o['actor'][0] = o['capo']
    assert call(o, 'GET', '/data?q=riservato').json()['notes'][0]['id'] == n['id']
    audit = o['db'].query(AuditLog).filter_by(target_type='notebook').one()
    assert audit.extra_data is None  # no title/content in the administrative log


def test_csrf_origin_owner_binding_and_extra_fields(operations, monkeypatch):
    o = operations
    body = dict(title='Test', request_key=uuid4().hex)
    assert o['client'].post('/appunti', json=body).status_code == 403
    for headers in (
        {'X-CSRF-Token': token(o['manager'])},
        {'X-CSRF-Token': token(o['capo']), 'Origin': 'https://attacker.test'},
        {'X-CSRF-Token': token(o['capo']), 'Sec-Fetch-Site': 'cross-site'},
    ):
        assert o['client'].post('/appunti', json=body, headers=headers).status_code == 403
    signed = token(o['capo'])
    import routes.notebook as routes
    with monkeypatch.context() as patch:
        patch.setattr(routes.time, 'time', lambda: 0)
        assert o['client'].post('/appunti', json=body, headers={'X-CSRF-Token': signed}).status_code == 403
    assert call(o, 'POST', body={**body, 'owner_id': o['manager'].id}).status_code == 422
    assert call(o, 'POST', body={**body, 'title': '   '}).status_code == 422
    assert o['db'].query(NotebookNote).count() == 0


def test_linked_site_permission_and_personal_space_for_worker(personnel):
    o = personnel
    assert call(o, 'POST', body=dict(title='Test', request_key=uuid4().hex, site_id=o['other'].id)).status_code == 403
    o['actor'][0] = o['staff']
    assert call(o, 'GET').status_code == 200
    n = create(o)
    assert call(o, 'GET', '/data').json()['sites'] == []
    assert call(o, 'GET', f"?cantiere={o['site'].id}").status_code == 404
    from services.personnel import today
    o['db'].add(ResourcePlan(site_id=o['site'].id, day=today(), resource_type='person',
        resource_id=o['worker'].id, resource_label='Worker', created_by_id=o['manager'].id))
    o['db'].commit()
    assert call(o, 'GET', f"?cantiere={o['site'].id}").status_code == 200
    assert edit(o, n, site_id=o['site'].id).status_code == 200
    assert o['client'].get('/mio-spazio/data').json()['assignments'][0]['site_id'] == o['site'].id
    assert '/appunti' in o['client'].get('/mio-spazio').text


def test_sharing_reader_editor_revocation_and_originals_owner_only(operations):
    o = operations
    n = create(o, collection='Privato')
    updated = edit(o, n, body='Testo pronto da mostrare').json()
    n = sharing(o, updated, [{'user_id': o['outsider'].id, 'permission': 'read'}]).json()
    notification = o['db'].query(Notification).filter_by(notification_type='notebook_shared').one()
    assert notification.recipient_user_id == o['outsider'].id
    assert n['title'] not in notification.message and 'P5' not in notification.message
    o['actor'][0] = o['outsider']
    shared = call(o, 'GET', f"/{n['id']}").json()
    assert shared['body'] == 'Testo pronto da mostrare'
    assert not shared['can_edit'] and not shared['owner'] and not shared['collection']
    assert 'draft' not in shared and not shared['grants']
    assert edit(o, shared, body='Reader cannot edit').status_code == 403
    assert call(o, 'GET', f"/{n['id']}/originali").status_code == 403
    assert sharing(o, n, []).status_code == 403
    assert call(o, 'PUT', f"/{n['id']}/archivio", dict(version=n['version'], archived=True)).status_code == 403
    o['actor'][0] = o['capo']
    n = sharing(o, n, [{'user_id': o['outsider'].id, 'permission': 'edit'}]).json()
    o['actor'][0] = o['outsider']
    shared = call(o, 'GET', f"/{n['id']}").json()
    assert shared['can_edit']
    assert edit(o, shared, site_id=o['other'].id).status_code == 403
    assert edit(o, shared, collection='X').status_code == 403
    n = edit(o, shared, body='Aggiornamento del collega').json()
    o['actor'][0] = o['capo']
    n = sharing(o, n, []).json()
    assert call(o, 'GET', f"/{n['id']}/originali").json()['revisions'][-1]['content']['body'].startswith('P5')
    o['actor'][0] = o['outsider']
    assert call(o, 'GET', f"/{n['id']}").status_code == 404
    revoked = o['client'].get(f"/appunti/{n['id']}", headers={'Accept': 'application/json'})
    assert revoked.status_code == 404 and 'Appunto non trovato' in revoked.json()['detail']
    assert call(o, 'GET', '/data?scope=received').json()['notes'] == []
    assert edit(o, shared, body='Revoked').status_code == 404


def test_create_retry_stale_writes_archive_and_search_literal(operations):
    o = operations
    key = uuid4().hex
    payload = dict(title='100%_test', request_key=key, body='originale')
    n = call(o, 'POST', body=payload).json()
    assert call(o, 'POST', body=payload).json()['id'] == n['id']
    assert o['db'].query(NotebookNote).count() == 1
    fresh = edit(o, n, body='nuovo').json()
    assert edit(o, n, body='stale').status_code == 409
    assert sharing(o, n, []).status_code == 409
    assert call(o, 'GET', '/data', params={'q': '%_'}).json()['notes'][0]['id'] == n['id']
    archived = call(o, 'PUT', f"/{n['id']}/archivio", dict(version=fresh['version'], archived=True)).json()
    assert call(o, 'GET', '/data').json()['notes'] == []
    assert call(o, 'GET', '/data?scope=archived').json()['notes'][0]['id'] == n['id']
    assert edit(o, archived, body='archived').status_code == 409
    assert not archived['can_edit']
    assert call(o, 'PUT', f"/{n['id']}/archivio", dict(version=archived['version'], archived=False)).json()['body'] == 'nuovo'


def test_invalid_recipients_are_atomic(operations):
    o = operations
    n = create(o)
    uid = o['outsider'].id
    for grants in (
        [{'user_id': o['capo'].id, 'permission': 'read'}],
        [{'user_id': uid, 'permission': 'read'}, {'user_id': uid, 'permission': 'edit'}],
        [{'user_id': 99999, 'permission': 'read'}],
    ):
        assert sharing(o, n, grants).status_code == 422
    o['outsider'].is_active = False
    o['db'].commit()
    assert sharing(o, n, [{'user_id': uid, 'permission': 'read'}]).status_code == 422
    assert o['db'].query(NotebookGrant).count() == o['db'].query(Notification).count() == 0
    assert call(o, 'GET', f"/{n['id']}").json()['version'] == n['version']


def configure(o, monkeypatch):
    monkeypatch.setenv('NOTES_OPENAI_API_KEY', 'isolated-fake-key')
    monkeypatch.setenv('NOTES_AI_USER_IDS', str(o['capo'].id))
    return dict(title='Verbale P5', body='Verificare P5: 6.3 m.', kind='meeting',
        details=svc.Details(actions=[svc.Action(text='Verificare la misura')]).model_dump(),
        warnings=['Misura da verificare'])


def prepare(o, n, **extra):
    return call(o, 'POST', f"/{n['id']}/riordina", dict(version=n['version'],
        request_key=uuid4().hex, mode='meeting', consent=True, **extra))


def test_ai_private_proposal_accept_preserves_original_and_never_creates_business_records(operations, monkeypatch):
    o = operations
    result = configure(o, monkeypatch)
    calls = []
    monkeypatch.setattr(ai, 'generate', lambda content, mode, key: calls.append(content) or result)
    n = create(o)
    key = uuid4().hex
    payload = dict(version=n['version'], request_key=key, mode='meeting', consent=True)
    draft = call(o, 'POST', f"/{n['id']}/riordina", payload).json()
    assert call(o, 'POST', f"/{n['id']}/riordina", payload).json()['id'] == draft['id']
    assert len(calls) == 1 and set(calls[0]) == {'title', 'kind', 'body', 'details'}
    original = call(o, 'GET', f"/{n['id']}").json()
    assert original['body'] == n['body'] and original['draft']['id'] == draft['id']
    r = call(o, 'POST', f"/{n['id']}/bozze/{draft['id']}/accetta", {'version': n['version']})
    assert r.status_code == 200, r.text
    accepted = r.json()
    assert accepted['kind'] == 'meeting' and accepted['body'] == result['body']
    assert not accepted['shared'] and accepted['draft'] is None
    assert call(o, 'GET', f"/{n['id']}/originali").json()['revisions'][0]['content']['body'] == n['body']
    assert o['db'].query(NotebookGrant).count() == o['db'].query(Report).count() == o['db'].query(SiteTask).count() == 0
    assert call(o, 'POST', f"/{n['id']}/bozze/{draft['id']}/accetta", {'version': accepted['version']}).status_code == 404


def test_ai_fail_closed_configuration_consent_permissions_shared_stale_and_discard(operations, monkeypatch):
    o = operations
    n = create(o)
    assert prepare(o, n).status_code == 503
    result = configure(o, monkeypatch)
    monkeypatch.setattr(ai, 'generate', lambda *args: result)
    assert call(o, 'POST', f"/{n['id']}/riordina", dict(version=n['version'], request_key=uuid4().hex,
        mode='meeting', consent=False)).status_code == 400
    o['actor'][0] = o['manager']
    assert prepare(o, n).status_code == 404
    o['actor'][0] = o['capo']
    draft = prepare(o, n).json()
    changed = edit(o, n, body='Aggiunta successiva').json()
    assert call(o, 'POST', f"/{n['id']}/bozze/{draft['id']}/accetta", {'version': changed['version']}).status_code == 409
    shared = sharing(o, changed, [{'user_id': o['outsider'].id, 'permission': 'edit'}]).json()
    assert shared['draft'] is None and prepare(o, shared).status_code == 409
    o['actor'][0] = o['outsider']
    assert prepare(o, shared).status_code == 403
    assert 'draft' not in call(o, 'GET', f"/{n['id']}").json()
    o['actor'][0] = o['capo']
    n = sharing(o, shared, []).json()
    draft = prepare(o, n).json()
    discarded = call(o, 'POST', f"/{n['id']}/bozze/{draft['id']}/scarta", {'version': n['version']}).json()
    assert discarded['body'] == 'Aggiunta successiva' and discarded['draft'] is None


def test_ai_provider_payload_and_errors_never_expose_secrets(monkeypatch):
    captured = []
    result = ai.Proposal(title='P5', body='6.3 m').model_dump()
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            captured.append((url, kwargs))
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'status': 'completed', 'output': [{'type': 'message', 'content': [
                    {'type': 'output_text', 'text': json.dumps(result)}]}]})
    monkeypatch.setattr(ai.httpx, 'Client', Client)
    content = svc.Content(title='P5', body='Appunto').model_dump()
    assert ai.generate(content, 'tidy', 'secret-test')['kind'] == 'free'
    url, sent = captured[0]
    assert url == 'https://api.openai.com/v1/responses'
    assert sent['json']['store'] is False and 'tools' not in sent['json']
    assert json.loads(sent['json']['input'])['note'] == content
    schema = sent['json']['text']['format']['schema']
    assert schema['additionalProperties'] is False and set(schema['required']) == set(schema['properties'])
    result['bad_field'] = 'never accept'
    with pytest.raises(HTTPException) as exc:
        ai.generate(content, 'tidy', 'secret-test')
    assert exc.value.status_code == 503 and 'secret-test' not in exc.value.detail


def test_ai_provider_failure_keeps_original_and_quota_prevents_repeat_calls(operations, monkeypatch):
    o = operations
    configure(o, monkeypatch)
    def fail(*args):
        raise HTTPException(503, 'Provider unavailable')
    monkeypatch.setattr(ai, 'generate', fail)
    n = create(o)
    assert prepare(o, n).status_code == 503
    assert o['db'].query(NotebookDraft).one().state == 'failed'
    assert call(o, 'GET', f"/{n['id']}").json()['body'] == n['body']
    key = f"{o['capo'].id}:day:{datetime.utcnow():%Y-%m-%d}"
    o['db'].query(NotebookAIQuota).filter_by(key=key).update({'count': 30})
    o['db'].commit()
    assert prepare(o, n).status_code == 429
    assert o['db'].query(NotebookDraft).count() == 1


def test_site_deletion_retains_private_notes_and_name_with_no_admin_access(operations):
    from test_site_deletion import prepare as prepare_site
    o = operations
    n = create(o, site_id=o['site'].id)
    sid = prepare_site(o)
    name = o['site'].name
    r = o['client'].post(f'/manager/cantieri/{sid}/elimina', data={'conferma_nome': name}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert call(o, 'GET', f"/{n['id']}").status_code == 404
    o['actor'][0] = o['capo']
    kept = call(o, 'GET', f"/{n['id']}").json()
    assert kept['site_id'] is None and kept['site'] == name and kept['body'] == n['body']
    assert kept['version'] == n['version']+1


def test_pages_and_data_are_never_cacheable(operations):
    for path in ('', '/data'):
        r = call(operations, 'GET', path)
        assert r.status_code == 200, r.text
        assert 'no-store' in r.headers['cache-control']


def test_storage_failure_does_not_log_private_sql_parameters(operations, monkeypatch, caplog):
    from sqlalchemy.exc import SQLAlchemyError
    def fail(*args, **kwargs):
        raise SQLAlchemyError('Private SQL parameters secret-original-text')
    monkeypatch.setattr(svc, 'create', fail)
    r = call(operations, 'POST', body=dict(title='Test', request_key=uuid4().hex))
    assert r.status_code == 503
    assert 'secret-original-text' not in r.text + caplog.text
