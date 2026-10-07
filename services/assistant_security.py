"""Independent bearer access for one configured administrator. Never accepts UI JWTs."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from auth import SECRET_KEY, get_current_active_user_html
from database import get_db
from models import AssistantRateBucket, User
from permissions import has_perm
from audit_utils import log_audit_event


@dataclass(frozen=True)
class Settings:
    owner_id: int
    token_hash: str
    origin: str
    expires_at: datetime


def settings() -> Settings:
    if os.getenv('ASSISTANT_API_ENABLED', '').lower() != 'true':
        raise HTTPException(404, 'Integrazione non attiva')
    try:
        owner = int(os.environ['ASSISTANT_OWNER_ID'])
        digest = os.environ['ASSISTANT_TOKEN_SHA256'].lower()
        origin = os.environ['ASSISTANT_PUBLIC_ORIGIN'].rstrip('/')
        expires = datetime.fromisoformat(os.environ['ASSISTANT_TOKEN_EXPIRES_AT'].replace('Z', '+00:00'))
        url = urlsplit(origin)
        valid = (owner > 0 and re.fullmatch(r'[a-f0-9]{64}', digest) and url.scheme == 'https'
                 and url.hostname and not url.username and not url.password
                 and not url.query and not url.fragment and not url.path and expires.tzinfo is not None)
        if not valid:
            raise ValueError()
    except (KeyError, ValueError):
        raise HTTPException(503, 'Configurazione integrazione incompleta')
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(503, 'Credenziale integrazione scaduta: rinnovare la configurazione')
    return Settings(owner, digest, origin, expires)


def check_owner(user: User | None, config: Settings) -> User:
    # No "all administrators" fallback. Losing active admin access revokes this channel.
    if not user or user.id != config.owner_id or not user.is_active or not has_perm(user, 'admin.access'):
        raise HTTPException(403, 'Accesso riservato al proprietario amministratore')
    return user


def rate_limit(db: Session, owner_id: int, writes: bool):
    window = int(time.time() // 60)
    key = f'{owner_id}:{"write" if writes else "read"}:{window}'
    limit = 20 if writes else 120
    try:
        with db.begin_nested():
            db.add(AssistantRateBucket(key=key, window=window, count=0))
            db.flush()
    except IntegrityError:
        pass
    updated = db.query(AssistantRateBucket).filter(
        AssistantRateBucket.key == key, AssistantRateBucket.count < limit,
    ).update({'count': AssistantRateBucket.count + 1}, synchronize_session=False)
    db.query(AssistantRateBucket).filter(AssistantRateBucket.window < window - 5).delete(synchronize_session=False)
    db.commit()
    if not updated:
        raise HTTPException(429, 'Limite richieste raggiunto', headers={'Retry-After': '60'})


def api_owner(request: Request, db: Session = Depends(get_db)) -> User:
    config = settings()
    header = request.headers.get('authorization', '')
    scheme, _, token = header.partition(' ')
    digest = hashlib.sha256(token.encode()).hexdigest()
    if scheme.lower() != 'bearer' or not token.startswith('lenta_assistant_') or len(token) < 58 or not hmac.compare_digest(digest, config.token_hash):
        raise HTTPException(401, 'Credenziale integrazione non valida', headers={'WWW-Authenticate': 'Bearer'})
    user = check_owner(db.get(User, config.owner_id), config)
    rate_limit(db, user.id, request.method != 'GET')
    log_audit_event(db, user, 'assistant.access', 'integration', extra_data={
        'method': request.method, 'path': request.url.path,
    })
    db.commit()
    return user


def browser_owner(user: User = Depends(get_current_active_user_html)) -> User:
    return check_owner(user, settings())


def csrf_token(proposal) -> str:
    message = f'assistant-approval:{proposal.id}:{proposal.owner_id}:{proposal.summary_hash}:{proposal.credential_hash}:{proposal.expires_at.isoformat()}'
    return hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


def validate_decision(request: Request, proposal, token: str):
    config = settings()
    # Approval is a separate browser-authenticated channel, not an API "confirmed" flag.
    if request.headers.get('authorization'):
        raise HTTPException(403, 'Confermare dalla sessione personale del gestionale')
    origin = request.headers.get('origin')
    if origin and origin != config.origin:
        raise HTTPException(403, 'Origine non autorizzata')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Richiesta non autorizzata')
    if not hmac.compare_digest(token, csrf_token(proposal)):
        raise HTTPException(403, 'Conferma non valida')
    if not hmac.compare_digest(proposal.credential_hash, config.token_hash):
        raise HTTPException(403, 'Credenziale revocata: preparare una nuova proposta')
    if proposal.state == 'pending' and proposal.expires_at <= datetime.utcnow():
        raise HTTPException(410, 'Proposta scaduta: preparare una nuova anteprima')
