"""Human review of operational fiches, independent of the assistant credential."""
import hashlib
import hmac
import json
import os
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from models import Fiche, FicheStratigrafia, Site, User, Notification
from permissions import has_perm


def can_review(user):
    owner = os.getenv('FICHE_REVIEW_OWNER_ID') or os.getenv('ASSISTANT_OWNER_ID')
    return bool(user and user.is_active and has_perm(user, 'admin.access')
                and (not owner or str(user.id) == owner))


def confirmed(fiche):
    return getattr(fiche, 'review_status', 'confirmed') in (None, 'confirmed')


def review_token(fiche, user):
    from auth import SECRET_KEY
    value = f'fiche-review:{fiche.id}:{fiche.review_revision}:{user.id}'
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def notify_review(db, fiche):
    from notifications import create_notifications_for_users
    users = [u for u in db.query(User).filter(User.is_active.is_(True)).all() if can_review(u)]
    site = db.get(Site, fiche.site_id)
    target = f'/manager/fiches/{fiche.id}'
    pending = [n for n in db.new if isinstance(n, Notification) and n.notification_type == 'fiche_review' and n.target_url == target]
    if pending:
        return pending
    db.query(Notification).filter(Notification.notification_type == 'fiche_review',
                                  Notification.target_url == target).update({'is_read': True})
    return create_notifications_for_users(db, users, 'fiche_review',
        f'{site.name if site else "Cantiere"} · Pannello {fiche.panel_label} · Fiche da confermare',
        target_url=target)


def confirm_fiche(db, fiche, user, token, request):
    if not can_review(user) or request.headers.get('authorization'):
        raise HTTPException(403, 'Conferma riservata al proprietario amministratore')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Origine non autorizzata')
    if not hmac.compare_digest(token, review_token(fiche, user)):
        raise HTTPException(409, 'La fiche è cambiata. Riaprila e ricontrolla i dati prima di confermare.')
    if confirmed(fiche):
        return
    from models.fiche_review import FicheReviewEvent
    # Same site lock as creation/grouped pours; revision also protects stale forms.
    site = db.query(Site).filter_by(id=fiche.site_id).with_for_update().one()
    changed = db.query(Fiche).filter_by(id=fiche.id, review_status='pending',
                                      review_revision=fiche.review_revision).update({
        'review_status': 'confirmed', 'reviewed_by_id': user.id,
        'reviewed_at': datetime.utcnow(), 'review_revision': fiche.review_revision + 1,
    }, synchronize_session=False)
    if changed != 1:
        raise HTTPException(409, 'La fiche è cambiata. Riaprila prima di confermare.')
    db.add(FicheReviewEvent(fiche_id=fiche.id, actor_id=user.id, action='confirmed',
                           changes=json.dumps({'revision': fiche.review_revision})))
    db.query(Notification).filter_by(notification_type='fiche_review',
        target_url=f'/manager/fiches/{fiche.id}').update({'is_read': True})
    db.expire(fiche)
    from main import _sync_site_fiche_progress
    _sync_site_fiche_progress(db, site)
    db.commit()


@event.listens_for(Session, 'before_flush')
def track_fiche_edits(db, flush_context, instances):
    """Catch every ORM edit, including joint pours and PDF/soil corrections."""
    from models.fiche_review import FicheReviewEvent
    affected = {}
    ignored = {'id', 'created_at', 'updated_at', 'review_status', 'review_revision',
               'reviewed_by_id', 'reviewed_at'}
    for row in list(db.dirty):
        if isinstance(row, Fiche):
            changes = {}
            for attr in inspect(row).mapper.column_attrs:
                if attr.key in ignored:
                    continue
                history = inspect(row).attrs[attr.key].history
                if history.has_changes():
                    changes[attr.key] = {'before': list(history.deleted), 'after': list(history.added)}
            if changes:
                affected[row] = changes
                for old_site in changes.get('site_id', {}).get('before', []):
                    db.info.setdefault('fiche_review_sites', set()).add(old_site)
    for row in list(db.new) + list(db.dirty) + list(db.deleted):
        if isinstance(row, FicheStratigrafia) and row.fiche_id:
            fiche = db.get(Fiche, row.fiche_id)
            if fiche and fiche not in db.new:
                affected.setdefault(fiche, {})['stratigrafia'] = 'changed'
    # Confirmation and every fiche writer acquire site locks before fiche rows.
    # Keeping this order avoids deadlocks when an evening review overlaps edits.
    sites = {f.site_id for f in affected}
    sites.update(db.info.get('fiche_review_sites', set()))
    sites.update(f.site_id for f in list(db.new) + list(db.deleted) if isinstance(f, Fiche))
    sites.discard(None)
    if sites:
        db.query(Site).filter(Site.id.in_(sites)).order_by(Site.id).with_for_update().all()
    for fiche, changes in affected.items():
        if fiche in db.deleted:
            continue
        fiche.review_status = 'pending'
        fiche.reviewed_at = None
        fiche.reviewed_by_id = None
        fiche.review_revision = (fiche.review_revision or 1) + 1
        db.add(FicheReviewEvent(fiche_id=fiche.id, actor_id=db.info.get('fiche_actor_id'),
                               action='edited', changes=json.dumps(changes, default=str)))
        db.info.setdefault('fiche_review_sites', set()).add(fiche.site_id)
        notify_review(db, fiche)
    for row in list(db.new) + list(db.deleted):
        if isinstance(row, Fiche):
            if row.site_id is not None:
                db.info.setdefault('fiche_review_sites', set()).add(row.site_id)


@event.listens_for(Session, 'after_flush_postexec')
def refresh_review_progress(db, flush_context):
    ids = db.info.pop('fiche_review_sites', set())
    if ids:
        from main import _sync_site_fiche_progress
        for ident in ids:
            site = db.get(Site, ident)
            if site:
                _sync_site_fiche_progress(db, site)


@event.listens_for(Session, 'after_soft_rollback')
def clear_review_progress(db, previous_transaction):
    db.info.pop('fiche_review_sites', None)
