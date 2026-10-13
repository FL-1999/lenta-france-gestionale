import hashlib
import hmac
import json
import secrets
import time
from datetime import date, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import or_
from auth import SECRET_KEY, get_current_active_user_html
from database import get_db
from models import (Personale, PersonalePresenza, User, Site, Depot, RoleEnum, PersonnelRequest,
    PersonnelTeam, PersonnelAssignment, PersonnelAttachment, PersonnelEvent, PersonnelAttendanceLink)
from permissions import has_perm, user_has_role
from template_context import register_manager_badges, render_template
from services import personnel as svc

router = APIRouter(tags=['personnel-workspace'])
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


class RequestInput(BaseModel):
    kind: Literal['leave', 'absence', 'correction']
    person_id: int | None = None
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(None, max_length=30)
    note: str = Field('', max_length=2000)
    submission_key: str = Field(min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')


class DecisionInput(BaseModel):
    version: int = Field(ge=1)
    status: str
    classification: str | None = None
    end_date: date | None = None
    response: str = Field('', max_length=2000)
    office_note: str = Field('', max_length=2000)
    include_weekends: bool = False
    original_received: bool = False


class TeamInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    lead_id: int
    site_id: int | None = None
    depot_id: int | None = None


class AssignmentInput(BaseModel):
    person_id: int
    start_date: date
    end_date: date | None = None


def token(user):
    value = f'{user.id}:{int(time.time())}:{secrets.token_hex(12)}'
    return value+':'+hmac.new(SECRET_KEY.encode(), ('personnel:'+value).encode(), hashlib.sha256).hexdigest()


def validate(request, user):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, 'Origine non autorizzata / Origine non autorisée')
    try:
        uid, stamp, nonce, signature = request.headers.get('x-csrf-token', '').split(':')
        expected = hmac.new(SECRET_KEY.encode(), f'personnel:{uid}:{stamp}:{nonce}'.encode(), hashlib.sha256).hexdigest()
        valid = uid == str(user.id) and 0 <= time.time()-int(stamp) <= 7200 and hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, 'Ricarica la pagina prima di salvare / Rechargez la page avant de sauvegarder')


def request_row(db, ident, user):
    row = db.get(PersonnelRequest, ident)
    if not row:
        raise HTTPException(404, 'Comunicazione non trovata / Communication introuvable')
    if not svc.office(user) and row.person_id != svc.own_person(db, user).id:
        raise HTTPException(403, 'Comunicazione riservata / Communication privée')
    return row


def request_data(db, row, user):
    attachment = db.query(PersonnelAttachment.id).filter_by(request_id=row.id).first()
    result = {key: getattr(row, key) for key in ['id', 'kind', 'reason', 'person_id', 'start_date', 'end_date',
        'note', 'status', 'classification', 'response', 'include_weekends', 'version', 'created_at']}
    result.update(name=svc.full_name(db.get(Personale, row.person_id)), attachment=bool(attachment),
        status_label=svc.STATUS_LABELS[row.status])
    if svc.office(user):
        conflicts = db.query(PersonalePresenza).filter(PersonalePresenza.personale_id == row.person_id,
            PersonalePresenza.attendance_date >= row.start_date,
            PersonalePresenza.attendance_date <= (row.end_date or svc.today())).all() if row.kind != 'correction' else []
        result['conflicts'] = [dict(id=p.id, day=p.attendance_date, status=p.status, hours=p.hours,
            report_id=p.report_id, snapshot=hashlib.sha256(svc.attendance_snapshot(p).encode()).hexdigest())
            for p in conflicts if not db.query(PersonnelAttendanceLink).filter_by(attendance_id=p.id).first()]
        result.update(office_note=row.office_note, original_received=row.original_received,
            events=[{'action': e.action, 'at': e.created_at, 'actor': db.get(User, e.actor_id).full_name or db.get(User, e.actor_id).email,
                     'details': e.details} for e in db.query(PersonnelEvent).filter_by(request_id=row.id).order_by(PersonnelEvent.id).all()])
    return result


def view(request, db, user, mode):
    if mode != 'personal': svc.require_office(user)
    return render_template(templates, request, 'personnel/workspace.html',
        {'personnel_mode': mode, 'csrf': token(user), 'today': svc.today()}, db, user)


@router.get('/mio-spazio', name='my_space')
def personal_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    return view(request, db, user, 'personal')


@router.get('/manager/personale/richieste', name='personnel_requests')
def office_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    return view(request, db, user, 'office')


@router.get('/manager/personale/squadre', name='personnel_teams')
def teams_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    return view(request, db, user, 'teams')


@router.get('/mio-spazio/data')
def personal_data(month: date | None = None, request_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    profile = svc.own_person(db, user)
    day = svc.today(); start = (month or day).replace(day=1)
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    attendance = db.query(PersonalePresenza).filter(PersonalePresenza.personale_id == profile.id,
        PersonalePresenza.attendance_date >= start, PersonalePresenza.attendance_date < end).order_by(PersonalePresenza.attendance_date.desc()).all()
    assignments = db.query(PersonnelAssignment).filter_by(person_id=profile.id).order_by(PersonnelAssignment.start_date.desc()).limit(100).all()
    def assignment_data(row):
        team = db.get(PersonnelTeam, row.team_id); lead = svc.team_lead(db, team)
        return dict(id=row.id, start=row.start_date, end=row.end_date, team=team.name, destination=svc.team_label(db, team),
            lead=lead.full_name or lead.email, current=team.active and row.start_date <= day and (row.end_date is None or row.end_date >= day))
    prepared_assignments = [assignment_data(a) for a in assignments]
    from models import ResourcePlan
    daily = db.query(ResourcePlan).filter_by(resource_type='person', resource_id=profile.id).filter(
        ResourcePlan.day >= day, ResourcePlan.day <= day+timedelta(days=60)).order_by(ResourcePlan.day).all()
    if any(p.day == day for p in daily):
        for a in prepared_assignments: a['current'] = False
    for plan in daily:
        site = db.get(Site, plan.site_id); lead = db.get(User, site.caposquadra_id) if site.caposquadra_id else None
        prepared_assignments.insert(0, dict(id=f'plan-{plan.id}', start=plan.day, end=plan.day,
            team='Assegnazione giornaliera / Affectation journalière', destination=site.name,
            lead=(lead.full_name or lead.email) if lead else '—', current=plan.day == day))
    requests = db.query(PersonnelRequest).filter_by(person_id=profile.id).order_by(PersonnelRequest.id.desc()).limit(100).all()
    if request_id and not any(r.id == request_id for r in requests):
        row = request_row(db, request_id, user)
        if row.person_id != profile.id: raise HTTPException(403)
        requests.insert(0, row)
    return {'person': {'id': profile.id, 'name': svc.full_name(profile)}, 'today': day, 'month': start,
        'assignments': prepared_assignments,
        'attendance': [dict(id=p.id, date=p.attendance_date, status=p.status, hours=p.hours,
            site=(db.get(Site, p.site_id).name if p.site_id and db.get(Site, p.site_id) else None),
            source='report' if p.report_id else 'office') for p in attendance],
        'requests': [request_data(db, r, user) for r in requests],
        'classifications': svc.CLASSIFICATIONS}


@router.get('/manager/personale/workspace-data')
def office_data(day: date | None = None, request_id: int | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); day = day or svc.today()
    people = db.query(Personale).order_by(Personale.cognome, Personale.nome).all()
    teams = db.query(PersonnelTeam).order_by(PersonnelTeam.name).all()
    requests = db.query(PersonnelRequest).order_by(PersonnelRequest.id.desc()).limit(200).all()
    if request_id and not any(r.id == request_id for r in requests):
        requests.insert(0, request_row(db, request_id, user))
    return {'day': day, 'classifications': svc.CLASSIFICATIONS,
        'people': [dict(id=p.id, name=svc.full_name(p), active=p.attivo, user_id=p.user_id) for p in people],
        'users': [dict(id=u.id, name=u.full_name or u.email) for u in db.query(User).filter(User.is_active.is_(True)).all()] if has_perm(user, 'users.manage') else [],
        'leads': [dict(id=u.id, name=u.full_name or u.email) for u in db.query(User).filter(User.is_active.is_(True)).all() if user_has_role(u, RoleEnum.caposquadra)],
        'sites': [dict(id=s.id, name=s.name) for s in db.query(Site).filter_by(is_active=True)],
        'depots': [dict(id=d.id, name=d.name) for d in db.query(Depot).filter_by(is_active=True)],
        'teams': [dict(id=t.id, name=t.name, destination=svc.team_label(db, t), lead_id=t.lead_id, site_id=t.site_id,
            lead=svc.team_lead(db, t).full_name or svc.team_lead(db, t).email,
            assignments=[dict(id=a.id, person_id=a.person_id, name=svc.full_name(db.get(Personale, a.person_id)),
                start=a.start_date, end=a.end_date, unavailable=bool(svc.unavailable(db, a.person_id, day)))
                for a in db.query(PersonnelAssignment).filter_by(team_id=t.id).order_by(PersonnelAssignment.start_date.desc()).all()]) for t in teams],
        'requests': [request_data(db, r, user) for r in requests]}


@router.post('/mio-spazio/richieste')
async def submit(request: Request, payload: str = Form(..., max_length=6000), attachment: UploadFile | None = File(None),
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    try:
        data = RequestInput.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(422, 'Controlla i dati richiesti / Vérifiez les données requises')
    content = await attachment.read(svc.MAX_ATTACHMENT+1) if attachment and attachment.filename else None
    try:
        row = svc.create_request(db, user, data, content); db.commit()
        return request_data(db, row, user)
    except Exception:
        db.rollback(); raise


@router.post('/mio-spazio/richieste/{ident}/allegato')
async def attach(ident: int, request: Request, attachment: UploadFile = File(...),
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user); row = request_row(db, ident, user)
    svc.person(db, row.person_id, True)
    try:
        svc.store_attachment(db, row, await attachment.read(svc.MAX_ATTACHMENT+1))
        svc.event(db, user, 'attachment_added', row.id); db.commit()
        return {'ok': True}
    except Exception:
        db.rollback(); raise


@router.get('/mio-spazio/richieste/{ident}/allegato')
def download(ident: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    row = request_row(db, ident, user)
    attachment = db.query(PersonnelAttachment).filter_by(request_id=row.id).first()
    if not attachment: raise HTTPException(404, 'Allegato non trovato / Pièce jointe introuvable')
    extension = {'application/pdf': 'pdf', 'image/png': 'png', 'image/jpeg': 'jpg'}[attachment.content_type]
    return Response(svc.cipher().decrypt(attachment.encrypted_data), media_type=attachment.content_type,
        headers={'Content-Disposition': f'attachment; filename="certificato-{ident}.{extension}"',
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/manager/personale/richieste/{ident}/esito')
def decision(ident: int, data: DecisionInput, request: Request,
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); validate(request, user)
    try:
        row = svc.decide(db, user, request_row(db, ident, user), data); db.commit()
        return request_data(db, row, user)
    except Exception:
        db.rollback(); raise


@router.post('/manager/personale/squadre')
def create_team(data: TeamInput, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); validate(request, user)
    try:
        row = svc.save_team(db, user, data); db.commit(); return {'id': row.id}
    except Exception:
        db.rollback(); raise


@router.post('/manager/personale/squadre/{ident}/assegnazioni')
def assign(ident: int, data: AssignmentInput, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); validate(request, user)
    try:
        row = svc.assign(db, user, ident, data); db.commit(); return {'id': row.id}
    except Exception:
        db.rollback(); raise


class EndAssignment(BaseModel):
    end_date: date


class ClearAttendance(BaseModel):
    attendance_id: int
    snapshot: str = Field(min_length=64, max_length=64)


@router.post('/manager/personale/richieste/{ident}/correggi-presenza')
def clear_conflict(ident: int, data: ClearAttendance, request: Request,
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); validate(request, user)
    row = request_row(db, ident, user); svc.person(db, row.person_id, True)
    presence = db.get(PersonalePresenza, data.attendance_id)
    if not presence or presence.personale_id != row.person_id or not row.start_date <= presence.attendance_date <= (row.end_date or svc.today()):
        raise HTTPException(409, 'Registrazione non pertinente / Saisie non concernée')
    if presence.report_id or db.query(PersonnelAttendanceLink).filter_by(attendance_id=presence.id).first():
        raise HTTPException(409, 'Correggi il documento di origine / Corrigez le document d’origine')
    if hashlib.sha256(svc.attendance_snapshot(presence).encode()).hexdigest() != data.snapshot:
        raise HTTPException(409, 'Presenza modificata: ricarica / Présence modifiée : rechargez')
    svc.event(db, user, 'manual_attendance_removed', row.id, attendance_id=presence.id, previous=svc.attendance_snapshot(presence))
    db.delete(presence); db.commit()
    return {'ok': True}


@router.post('/manager/personale/assegnazioni/{ident}/fine')
def end_assignment(ident: int, data: EndAssignment, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.require_office(user); validate(request, user)
    row = db.get(PersonnelAssignment, ident)
    if not row: raise HTTPException(404)
    svc.person(db, row.person_id, True)
    if data.end_date < row.start_date: raise HTTPException(422, 'La fine precede l’inizio / La fin précède le début')
    # End/shorten an assignment; extending requires overlap checks through a new assignment.
    if row.end_date and data.end_date > row.end_date: raise HTTPException(409, 'Crea una nuova assegnazione per prolungare / Créez une nouvelle affectation')
    row.end_date = data.end_date
    svc.event(db, user, 'assignment_ended', assignment_id=row.id, end=row.end_date)
    db.commit(); return {'ok': True}


class LinkAccount(BaseModel):
    user_id: int


@router.post('/manager/personale/{ident}/account')
def link(ident: int, data: LinkAccount, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    if not has_perm(user, 'users.manage'): raise HTTPException(403)
    validate(request, user); target = db.query(User).filter_by(id=data.user_id).with_for_update().first()
    if not target or not target.is_active: raise HTTPException(422, 'Account non attivo / Compte inactif')
    row = svc.person(db, ident, True)
    if row.user_id and row.user_id != target.id or db.query(Personale).filter(Personale.user_id == target.id, Personale.id != row.id).first():
        raise HTTPException(409, 'Collegamento già presente: verifica i profili senza duplicarli / Liaison existante : vérifiez les profils')
    row.user_id = target.id
    svc.event(db, user, 'account_linked', person_id=row.id, user_id=target.id)
    db.commit(); return {'ok': True}


@router.get('/capo/squadra')
def roster(site_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    site = db.get(Site, site_id)
    if not site or not site.is_active: raise HTTPException(404)
    if not svc.office(user) and (user.role != RoleEnum.caposquadra or site.caposquadra_id != user.id): raise HTTPException(403)
    team, rows = svc.effective_roster(db, site_id, day)
    return {'team': team.name if team else None, 'csrf': token(user), 'people': [dict(id=a.id, name=svc.full_name(a),
        unavailable=bool(svc.unavailable(db, a.id, day))) for a in rows]}


class CapoAbsence(BaseModel):
    site_id: int
    person_id: int
    day: date
    submission_key: str = Field(min_length=16, max_length=64)


@router.post('/capo/squadra/assenza')
def capo_absence(data: CapoAbsence, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    roster_data = roster(data.site_id, data.day, db, user)
    if data.person_id not in {p['id'] for p in roster_data['people']}: raise HTTPException(403)
    target = svc.person(db, data.person_id, True)
    existing = db.query(PersonnelRequest).filter_by(created_by_id=user.id, submission_key=data.submission_key).first()
    if existing: return {'id': existing.id}
    row = PersonnelRequest(person_id=target.id, created_by_id=user.id, submission_key=data.submission_key,
        kind='absence', reason='other', start_date=data.day, end_date=data.day, status='reported', note='Assenza segnalata dal caposquadra / Absence signalée par le chef d’équipe')
    db.add(row); db.flush(); svc.event(db, user, 'reported_by_lead', row.id, site_id=data.site_id)
    svc.notify_office(db, row, f'{svc.full_name(target)} · Assenza da verificare / Absence à vérifier')
    db.commit(); return {'id': row.id}
