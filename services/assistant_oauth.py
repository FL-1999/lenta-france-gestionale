"""OAuthLib authorization-code + mandatory S256 PKCE, one owner, revocable grants."""
from datetime import datetime, timedelta
import hashlib
import hmac
import logging
import re
import secrets
from types import SimpleNamespace

from fastapi import HTTPException
from oauthlib.oauth2 import RequestValidator, Server

from auth import SECRET_KEY
from models import (AssistantOAuthClient, AssistantOAuthCode, AssistantOAuthFlow,
                    AssistantOAuthGrant, AssistantOAuthToken, User)
from services.assistant_security import settings, check_owner

# OAuthLib's DEBUG diagnostics can include token request bodies.
logging.getLogger('oauthlib').setLevel(logging.WARNING)
ROOT = '/integrations/assistant/oauth'
MCP = '/integrations/assistant/mcp'
SCOPES = ('lenta.read', 'lenta.prepare', 'lenta.fiches.submit')
RESUME_COOKIE = 'lenta_oauth_resume'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def resource():
    return settings().origin + MCP


def sign(value):
    return hmac.new(SECRET_KEY.encode(), ('lenta-oauth:' + value).encode(), hashlib.sha256).hexdigest()


def flow_csrf(flow, user):
    return sign(f'consent:{flow.id}:{user.id}:{flow.expires_at.isoformat()}')


def resume_path(request):
    value = request.cookies.get(RESUME_COOKIE, '')
    ident, _, signature = value.partition('.')
    if re.fullmatch(r'[a-f0-9]{64}', ident) and hmac.compare_digest(signature, sign('resume:' + ident)):
        return ROOT + '/authorize?flow=' + ident
    return None


def valid_redirect(value):
    # Exact ChatGPT HTTPS callback family only. No query, fragment, userinfo or ports.
    return isinstance(value, str) and bool(re.fullmatch(
        r'https://chatgpt\.com/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]{1,128})', value))


def valid_grant(db, grant):
    cfg = settings()
    if (not grant or grant.revoked or grant.expires_at <= datetime.utcnow()
            or grant.credential_hash != cfg.token_hash or grant.resource != resource()):
        return None
    try:
        return check_owner(db.get(User, grant.owner_id), cfg)
    except HTTPException:
        return None


def access_owner(db, token, scope):
    row = db.get(AssistantOAuthToken, digest(token)) if token.startswith('lenta_mcp_') else None
    grant = db.get(AssistantOAuthGrant, row.grant_id) if row else None
    user = valid_grant(db, grant)
    if not row or row.rotated or row.expires_at <= datetime.utcnow() or not user:
        raise HTTPException(401, 'Collegamento scaduto o revocato', headers={
            'WWW-Authenticate': f'Bearer resource_metadata="{settings().origin}/.well-known/oauth-protected-resource{MCP}", error="invalid_token"'})
    if scope and scope not in grant.scope.split():
        raise HTTPException(403, 'Permesso non autorizzato', headers={
            'WWW-Authenticate': f'Bearer error="insufficient_scope", scope="{scope}"'})
    return user


class Validator(RequestValidator):
    def __init__(self, db):
        self.db = db

    def validate_client_id(self, client_id, request, *args, **kwargs):
        row = self.db.get(AssistantOAuthClient, client_id) if client_id else None
        if row:
            request.client = SimpleNamespace(client_id=client_id, row=row)
        return bool(row)

    def authenticate_client_id(self, client_id, request, *args, **kwargs):
        return self.validate_client_id(client_id, request)

    def client_authentication_required(self, request, *args, **kwargs):
        return False  # Public client: mandatory PKCE, no shared client secret.

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        return valid_redirect(redirect_uri) and redirect_uri in request.client.row.redirect_uris

    def get_default_redirect_uri(self, client_id, request, *args, **kwargs):
        return None  # An explicit, registered redirect is required on every flow.

    def validate_response_type(self, client_id, response_type, client, request, *args, **kwargs):
        return response_type == 'code'

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in ('authorization_code', 'refresh_token')

    def get_default_scopes(self, client_id, request, *args, **kwargs):
        return list(SCOPES)

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        return bool(scopes) and set(scopes).issubset(SCOPES)

    def is_pkce_required(self, client_id, request, *args, **kwargs):
        return True

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.db.add(AssistantOAuthCode(code_hash=digest(code['code']), client_id=client_id,
            owner_id=request.user.id, credential_hash=settings().token_hash,
            redirect_uri=request.redirect_uri, challenge=request.code_challenge,
            scope=' '.join(request.scopes), resource=resource(),
            expires_at=datetime.utcnow() + timedelta(minutes=2)))

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        row = self.db.query(AssistantOAuthCode).filter_by(code_hash=digest(code)).with_for_update().first()
        if not row or row.client_id != client_id:
            return False
        if row.consumed:
            if row.grant_id:
                self.db.query(AssistantOAuthGrant).filter_by(id=row.grant_id).update({'revoked': True})
            return False
        if (row.expires_at <= datetime.utcnow() or row.credential_hash != settings().token_hash
                or request.resource != row.resource):
            return False
        try:
            request.user = check_owner(self.db.get(User, row.owner_id), settings())
        except HTTPException:
            return False
        request.scopes = row.scope.split()
        request.code_row = row
        return True

    def get_code_challenge(self, code, request):
        return request.code_row.challenge

    def get_code_challenge_method(self, code, request):
        return 'S256'

    def confirm_redirect_uri(self, client_id, code, redirect_uri, client, request, *args, **kwargs):
        return hmac.compare_digest(redirect_uri, request.code_row.redirect_uri)

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        request.code_row.consumed = True

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        row = self.db.query(AssistantOAuthToken).filter_by(refresh_hash=digest(refresh_token)).with_for_update().first()
        grant = self.db.get(AssistantOAuthGrant, row.grant_id) if row else None
        if not grant or grant.client_id != client.client_id:
            return False
        if row.rotated:
            grant.revoked = True  # Refresh replay revokes the entire connection.
            return False
        user = valid_grant(self.db, grant)
        if not user or request.resource != grant.resource:
            return False
        request.user, request.grant, request.old_token = user, grant, row
        return True

    def get_original_scopes(self, refresh_token, request, *args, **kwargs):
        return request.grant.scope.split()

    def save_bearer_token(self, token, request, *args, **kwargs):
        now = datetime.utcnow()
        if request.grant_type == 'refresh_token':
            grant = request.grant
            request.old_token.rotated = True
            # A refresh may reduce, never expand, the granted scopes.
            grant.scope = ' '.join(request.scopes)
        else:
            grant = AssistantOAuthGrant(id=secrets.token_hex(32), owner_id=request.user.id,
                client_id=request.client_id, credential_hash=settings().token_hash,
                scope=' '.join(request.scopes), resource=resource(),
                expires_at=min(now + timedelta(days=90), settings().expires_at.replace(tzinfo=None)))
            self.db.add(grant)
            self.db.flush()
            request.code_row.grant_id = grant.id
        self.db.add(AssistantOAuthToken(access_hash=digest(token['access_token']),
            refresh_hash=digest(token['refresh_token']), grant_id=grant.id,
            expires_at=min(now + timedelta(seconds=token['expires_in']), grant.expires_at)))


def oauth_server(db):
    return Server(Validator(db), token_expires_in=900,
        token_generator=lambda request: 'lenta_mcp_' + secrets.token_urlsafe(48),
        refresh_token_generator=lambda request: 'lenta_refresh_' + secrets.token_urlsafe(48))
