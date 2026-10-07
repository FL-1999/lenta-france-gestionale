"""OAuth discovery, registration and explicit owner consent for ChatGPT."""
from datetime import datetime, timedelta
import hmac
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from oauthlib.oauth2 import OAuth2Error
from sqlalchemy.orm import Session

from auth import get_current_user_html
from database import get_db
from models import AssistantOAuthClient, AssistantOAuthFlow, AssistantOAuthGrant
from services.assistant_security import browser_owner, check_owner, rate_limit, settings
from services.assistant_oauth import ROOT, MCP, SCOPES, RESUME_COOKIE, sign, flow_csrf, valid_redirect, resource, oauth_server
from audit_utils import log_audit_event

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory='templates')


def private_json(value, status=200):
    return JSONResponse(value, status_code=status, headers={'Cache-Control': 'no-store'})


@router.get('/.well-known/oauth-protected-resource')
@router.get('/.well-known/oauth-protected-resource' + MCP)
def protected_metadata():
    return private_json({'resource': resource(), 'authorization_servers': [settings().origin],
        'scopes_supported': list(SCOPES), 'bearer_methods_supported': ['header'],
        'resource_name': 'Lenta — assistente personale'})


@router.get('/.well-known/oauth-authorization-server')
def authorization_metadata():
    base = settings().origin
    return private_json({'issuer': base, 'authorization_endpoint': base + ROOT + '/authorize',
        'token_endpoint': base + ROOT + '/token', 'registration_endpoint': base + ROOT + '/register',
        'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256'],
        'scopes_supported': list(SCOPES), 'authorization_response_iss_parameter_supported': True})


@router.post(ROOT + '/register')
async def register(request: Request, db: Session = Depends(get_db)):
    # Registration publishes client metadata, never access to business data.
    rate_limit(db, 0, True)
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        return private_json({'error': 'invalid_client_metadata'}, 400)
    if not isinstance(body, dict):
        return private_json({'error': 'invalid_client_metadata'}, 400)
    redirects = body.get('redirect_uris')
    grants = body.get('grant_types', ['authorization_code'])
    if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 4
            or not all(valid_redirect(u) for u in redirects)
            or body.get('token_endpoint_auth_method', 'none') != 'none'
            or not isinstance(grants, list) or not all(isinstance(g, str) for g in grants)
            or not set(grants).issubset({'authorization_code', 'refresh_token'})
            or body.get('response_types', ['code']) != ['code']):
        return private_json({'error': 'invalid_client_metadata', 'error_description': 'Richiesto client ChatGPT pubblico con PKCE e callback HTTPS registrato.'}, 400)
    ident = secrets.token_hex(32)
    db.add(AssistantOAuthClient(id=ident, redirect_uris=redirects))
    db.commit()
    return private_json({'client_id': ident, 'client_name': 'ChatGPT — Lenta personale',
        'redirect_uris': redirects, 'grant_types': ['authorization_code', 'refresh_token'],
        'response_types': ['code'], 'token_endpoint_auth_method': 'none',
        'scope': ' '.join(SCOPES)}, 201)


def authorize_uri(params):
    return settings().origin + ROOT + '/authorize?' + urlencode(params)


def validated_params(pairs, db):
    params = dict(pairs)
    allowed = {'client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'resource',
               'code_challenge', 'code_challenge_method'}
    if (len(params) != len(pairs) or not set(params).issubset(allowed)
            or any(len(v) > 2048 for v in params.values())
            or params.get('resource') != resource() or not params.get('state')
            or params.get('code_challenge_method') != 'S256'
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', params.get('code_challenge', ''))):
        raise HTTPException(400, 'Richiesta OAuth non valida: occorrono resource, state e PKCE S256.')
    try:
        oauth_server(db).validate_authorization_request(authorize_uri(params))
    except OAuth2Error as exc:
        raise HTTPException(400, exc.error)
    return params


@router.get(ROOT + '/authorize')
async def authorize(request: Request, db: Session = Depends(get_db)):
    ident = request.query_params.get('flow')
    if ident:
        flow = db.get(AssistantOAuthFlow, ident)
    else:
        params = validated_params(list(request.query_params.multi_items()), db)
        rate_limit(db, 0, True)
        flow = AssistantOAuthFlow(id=secrets.token_hex(32), params=params,
            expires_at=datetime.utcnow() + timedelta(minutes=10))
        db.add(flow)
        db.query(AssistantOAuthFlow).filter(AssistantOAuthFlow.expires_at < datetime.utcnow()).delete()
        db.commit()
    if not flow or flow.consumed or flow.expires_at <= datetime.utcnow():
        raise HTTPException(410, 'Collegamento scaduto. Riparti da ChatGPT.')
    try:
        user = await get_current_user_html(request, db)
    except HTTPException as exc:
        if exc.status_code != 303:
            raise
        response = RedirectResponse('/login', status_code=303)
        response.set_cookie(RESUME_COOKIE, flow.id + '.' + sign('resume:' + flow.id),
            max_age=600, secure=True, httponly=True, samesite='lax', path='/')
        return response
    check_owner(user, settings())
    response = templates.TemplateResponse(request, 'integrations/assistant_connection.html', {
        'flow': flow, 'csrf': flow_csrf(flow, user), 'user': user,
        'scopes': flow.params.get('scope', ' '.join(SCOPES)).split(), 'grants': None})
    response.delete_cookie(RESUME_COOKIE, path='/')
    return response


def same_origin(request):
    if (request.headers.get('authorization') or request.headers.get('sec-fetch-site') == 'cross-site'
            or request.headers.get('origin', settings().origin) != settings().origin):
        raise HTTPException(403, 'Autorizza dalla tua sessione personale Lenta')


def issuer_redirect(url):
    parsed = urlsplit(url)
    params = parse_qsl(parsed.query) + [('iss', settings().origin)]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ''))


@router.post(ROOT + '/authorize')
def consent(request: Request, flow_id: str = Form(..., max_length=64),
            csrf: str = Form(..., max_length=64), decision: str = Form(..., max_length=10),
            db: Session = Depends(get_db), user=Depends(browser_owner)):
    same_origin(request)
    row = db.query(AssistantOAuthFlow).filter_by(id=flow_id).with_for_update().first()
    if not row or row.consumed or row.expires_at <= datetime.utcnow():
        raise HTTPException(410, 'Collegamento scaduto o già utilizzato')
    if not hmac.compare_digest(csrf, flow_csrf(row, user)) or decision not in ('allow', 'deny'):
        raise HTTPException(403, 'Conferma non valida')
    validated_params(list(row.params.items()), db)
    # Conditional consume also protects SQLite and stale copies of the consent form.
    changed = db.query(AssistantOAuthFlow).filter_by(id=row.id, consumed=False).update({'consumed': True})
    if changed != 1:
        raise HTTPException(409, 'Collegamento già utilizzato')
    if decision == 'deny':
        location = row.params['redirect_uri'] + '?' + urlencode({'error': 'access_denied', 'state': row.params['state']})
    else:
        headers, body, status = oauth_server(db).create_authorization_response(authorize_uri(row.params),
            scopes=row.params.get('scope', ' '.join(SCOPES)).split(), credentials={'user': user})
        location = headers['Location']
    log_audit_event(db, user, 'assistant.oauth.' + decision, 'integration', extra_data={'client_id': row.params['client_id']})
    db.commit()
    return RedirectResponse(issuer_redirect(location), status_code=303)


@router.post(ROOT + '/token')
async def token(request: Request, db: Session = Depends(get_db)):
    rate_limit(db, 0, False)
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        return private_json({'error': 'invalid_request'}, 400)
    form = await request.form()
    pairs = list(form.multi_items())
    params = dict(pairs)
    if (len(params) != len(pairs) or not all(isinstance(v, str) and len(v) <= 2048 for v in params.values())
            or params.get('resource') != resource() or request.headers.get('authorization')
            or params.get('grant_type') not in ('authorization_code', 'refresh_token')
            or (params.get('grant_type') == 'authorization_code' and
                not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', params.get('code_verifier', '')))):
        return private_json({'error': 'invalid_request'}, 400)
    headers, body, status = oauth_server(db).create_token_response(settings().origin + ROOT + '/token',
        http_method='POST', body=urlencode(pairs), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    # Commit replay revocations even when OAuthLib returns invalid_grant.
    db.commit()
    return Response(body, status_code=status, headers=headers, media_type='application/json')


@router.get('/integrations/assistant/connections')
def connections(request: Request, db: Session = Depends(get_db), user=Depends(browser_owner)):
    grants = db.query(AssistantOAuthGrant).filter_by(owner_id=user.id, revoked=False).filter(
        AssistantOAuthGrant.expires_at > datetime.utcnow(),
        AssistantOAuthGrant.credential_hash == settings().token_hash).all()
    return templates.TemplateResponse(request, 'integrations/assistant_connection.html', {
        'flow': None, 'user': user, 'grants': grants, 'csrf': sign('revoke:' + str(user.id)), 'scopes': []})


@router.post('/integrations/assistant/connections/revoke')
def revoke(request: Request, csrf: str = Form(..., max_length=64),
           db: Session = Depends(get_db), user=Depends(browser_owner)):
    same_origin(request)
    if not hmac.compare_digest(csrf, sign('revoke:' + str(user.id))):
        raise HTTPException(403, 'Conferma non valida')
    db.query(AssistantOAuthGrant).filter_by(owner_id=user.id).update({'revoked': True})
    log_audit_event(db, user, 'assistant.oauth.revoked', 'integration')
    db.commit()
    return RedirectResponse('/integrations/assistant/connections', status_code=303)
