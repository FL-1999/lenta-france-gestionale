"""Concrete alerts share the fiche's geometry, transaction and site lock."""
import hashlib
import hmac
import json
from datetime import datetime
from math import isclose, isfinite, pi

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session
from models import Fiche, FicheConsumptionAlert, FicheReviewEvent, Notification, Site, User
from permissions import has_perm

NOTIFICATION_TYPE = 'fiche_consumption'


def can_validate(user):
    return bool(user and user.is_active and has_perm(user, 'manager.access'))


def theoretical_volume(fiche):
    if fiche.profondita_totale is None:
        return None
    kind = (fiche.tipologia_scavo or '').strip().lower()
    if kind == 'paratia' and fiche.larghezza_pannello is not None and fiche.altezza_pannello is not None:
        return fiche.larghezza_pannello * fiche.altezza_pannello * fiche.profondita_totale
    if kind == 'palo' and fiche.diametro_palo is not None:
        return pi * (fiche.diametro_palo / 2) ** 2 * fiche.profondita_totale
    return None


def consumption(fiche):
    fields = ('site_id', 'tipologia_scavo', 'profondita_totale', 'larghezza_pannello',
              'altezza_pannello', 'diametro_palo', 'metri_cubi_gettati')
    values = {key: getattr(fiche, key) for key in fields}
    for key in fields[2:]:
        values[key] = float(values[key]) if values[key] is not None else None
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    theoretical, actual = theoretical_volume(fiche), fiche.metri_cubi_gettati
    valid = theoretical is not None and actual is not None and isfinite(theoretical) and isfinite(actual) and theoretical > 0
    difference = actual - theoretical if valid else None
    percentage = difference / theoretical * 100 if valid else None
    kind = None
    if valid:
        # Ignore only floating-point noise, not a display-rounding tolerance.
        if actual < theoretical and not isclose(actual, theoretical, rel_tol=1e-12, abs_tol=1e-9):
            kind = 'shortage'
        elif actual > theoretical * 1.2 and not isclose(actual, theoretical * 1.2, rel_tol=1e-12, abs_tol=1e-9):
            kind = 'excess'
    return dict(fingerprint=fingerprint, kind=kind, theoretical=theoretical, actual=actual,
                difference=difference, percentage=percentage, comparable=valid)


def alert_url(fiche_id):
    return f'/manager/fiches/{fiche_id}#fiche-consumption'


def _notifications(db, fiche_id):
    return db.query(Notification).filter_by(notification_type=NOTIFICATION_TYPE, target_url=alert_url(fiche_id))


def _resolve_notifications(db, fiche_id):
    _notifications(db, fiche_id).update({'is_read': True}, synchronize_session='fetch')
    for row in db.new:
        if isinstance(row, Notification) and row.notification_type == NOTIFICATION_TYPE and row.target_url == alert_url(fiche_id):
            row.is_read = True


def sync_alert(db, fiche):
    """Caller holds the site's lock. No commit and no changes to the fiche itself."""
    metrics = consumption(fiche)
    row = db.get(FicheConsumptionAlert, fiche.id)
    if row is None:
        row = next((r for r in db.new if isinstance(r, FicheConsumptionAlert) and r.fiche_id == fiche.id), None)
    if row is None and not metrics['kind']:
        return None
    changed = row is None or row.fingerprint != metrics['fingerprint']
    if changed:
        _resolve_notifications(db, fiche.id)
        if row is None:
            row = FicheConsumptionAlert(fiche_id=fiche.id)
        row.fingerprint = metrics['fingerprint']
        row.status = 'pending' if metrics['kind'] else 'resolved'
        row.validated_at = row.validated_by_id = row.validated_by_name = None
        row.updated_at = datetime.utcnow()
        db.add(row)
    if row.status != 'pending':
        return row
    from notifications import create_notification
    recipients = [u for u in db.query(User).filter(User.is_active.is_(True)).all() if can_validate(u)]
    existing = {n.recipient_user_id for n in _notifications(db, fiche.id).filter_by(is_read=False)}
    existing.update(n.recipient_user_id for n in db.new if isinstance(n, Notification)
                    and n.notification_type == NOTIFICATION_TYPE and n.target_url == alert_url(fiche.id) and not n.is_read)
    site = db.get(Site, fiche.site_id)
    delta = f"{abs(metrics['difference']):.2f}".replace('.', ',')
    percent = f"{metrics['percentage']:+.1f}".replace('.', ',')
    description = (f'{delta} m³ in meno / manquants' if metrics['kind'] == 'shortage'
                   else f'+{delta} m³ · {percent}% (>20%)')
    message = f'Consumo calcestruzzo / Consommation béton · {site.name if site else ""} · {fiche.panel_label} · {description} · Da validare / À valider'
    for user in recipients:
        if user.id not in existing:
            create_notification(db, NOTIFICATION_TYPE, message, recipient_user_id=user.id, target_url=alert_url(fiche.id))
    return row


def view(db, fiche, stored=None):
    metrics = consumption(fiche)
    row = stored.get(fiche.id) if stored is not None else db.get(FicheConsumptionAlert, fiche.id)
    validated = bool(metrics['kind'] and row and row.status == 'validated' and row.fingerprint == metrics['fingerprint'])
    return dict(**metrics, active=bool(metrics['kind'] and not validated), validated=validated,
                validated_by=row.validated_by_name if validated else None,
                validated_at=row.validated_at if validated else None)


def validation_token(fiche, user):
    from auth import SECRET_KEY
    value = f"fiche-consumption:{fiche.id}:{fiche.review_revision}:{consumption(fiche)['fingerprint']}:{user.id}"
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def validate(db, fiche, user, token, request):
    if not can_validate(user) or request.headers.get('authorization'):
        raise HTTPException(403, 'Validazione riservata ad admin e manager nel gestionale')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Origine non autorizzata')
    site_id = fiche.site_id
    db.query(Site).filter_by(id=site_id).with_for_update().one()
    db.refresh(fiche)  # Check the latest values after the same lock taken by writers.
    if fiche.site_id != site_id or not hmac.compare_digest(token, validation_token(fiche, user)):
        raise HTTPException(409, 'La fiche è cambiata. Riaprila e ricontrolla il consumo.')
    row = sync_alert(db, fiche)
    if row is not None and row.status == 'pending':
        row.status = 'validated'
        row.validated_by_id = user.id
        row.validated_by_name = user.full_name or user.email
        row.validated_at = row.updated_at = datetime.utcnow()
        db.add(FicheReviewEvent(fiche_id=fiche.id, actor_id=user.id, action='consumption_validated',
                               changes=json.dumps(consumption(fiche))))
        _resolve_notifications(db, fiche.id)
    db.commit()


def site_summary(db, fiches):
    records = {r.fiche_id: r for r in db.query(FicheConsumptionAlert).filter(FicheConsumptionAlert.fiche_id.in_([f.id for f in fiches]))} if fiches else {}
    rows = [dict(view(db, f, records), fiche_id=f.id, panel=f.panel_label) for f in fiches]
    comparable = [r for r in rows if r['comparable']]
    theoretical = sum(r['theoretical'] for r in comparable)
    actual = sum(r['actual'] for r in comparable)
    return dict(theoretical=theoretical, actual=actual, difference=actual-theoretical,
                percentage=(actual-theoretical)/theoretical*100 if theoretical else None,
                included=len(comparable), missing=len(rows)-len(comparable),
                pending=[r for r in rows if r['active']], validated=sum(r['validated'] for r in rows))


def backfill(factory):
    """Idempotent startup reconciliation also detects already saved anomalies."""
    with factory() as db:
        sites = [r[0] for r in db.query(Fiche.site_id).distinct()]
    for site_id in sorted(sites):
        with factory() as db:
            db.query(Site).filter_by(id=site_id).with_for_update().one()
            for fiche in db.query(Fiche).filter_by(site_id=site_id).all():
                sync_alert(db, fiche)
            db.commit()


@event.listens_for(Session, 'before_flush')
def collect_changes(db, flush_context, instances):
    candidates = db.info.setdefault('fiche_consumption_changes', set())
    candidates.update(row for row in list(db.new) + list(db.dirty) if isinstance(row, Fiche) and row not in db.deleted)
    for row in list(db.deleted):
        if isinstance(row, Fiche):
            candidates.discard(row)
            db.info.setdefault('fiche_consumption_deleted', set()).add(row.id)


@event.listens_for(Session, 'after_flush_postexec')
def sync_changes(db, flush_context):
    for fiche_id in db.info.pop('fiche_consumption_deleted', set()):
        _resolve_notifications(db, fiche_id)
        db.query(FicheConsumptionAlert).filter_by(fiche_id=fiche_id).delete(synchronize_session='fetch')
    for fiche in db.info.pop('fiche_consumption_changes', set()):
        sync_alert(db, fiche)


@event.listens_for(Session, 'after_soft_rollback')
def clear_changes(db, previous_transaction):
    db.info.pop('fiche_consumption_changes', None)
    db.info.pop('fiche_consumption_deleted', None)
