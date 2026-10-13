"""Shared personnel rules. Callers own transactions; no writes to payroll balances."""
import base64
import hashlib
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import or_
from models import (Personale, PersonalePresenza, PersonnelRequest, PersonnelAttachment,
    PersonnelAttendanceLink, PersonnelEvent, PersonnelTeam, PersonnelAssignment,
    Site, Depot, User, RoleEnum)
from permissions import has_perm, user_has_role
from notifications import create_notification

CLASSIFICATIONS = {'FERIE': 'Ferie / Congé payé', 'CONGE_SANS_SOLDE': 'Congé sans solde',
    'MALATTIA': 'Malattia / Maladie', 'PERMESSO': 'Permesso / Autorisation',
    'ASSENZA': 'Altra assenza / Autre absence'}
STATUS_LABELS = {'pending': 'In attesa', 'reported': 'Segnalata', 'approved': 'Approvata',
    'rejected': 'Rifiutata', 'acknowledged': 'Presa in carico', 'cancelled': 'Annullata', 'closed': 'Verificata'}
MAX_ATTACHMENT = 5 * 1024 * 1024


def today():
    return datetime.now(ZoneInfo('Europe/Paris')).date()


def office(user):
    return bool(user and user.is_active and has_perm(user, 'manager.access'))


def require_office(user):
    if not office(user):
        raise HTTPException(403, 'Accesso riservato all’ufficio / Accès réservé au bureau')


def person(db, ident, lock=False):
    query = db.query(Personale).filter_by(id=ident)
    row = (query.with_for_update().populate_existing() if lock else query).first()
    if not row or not row.attivo:
        raise HTTPException(409, 'Profilo personale non attivo / Profil personnel inactif')
    return row


def own_person(db, user):
    row = db.query(Personale).filter_by(user_id=user.id, attivo=True).first()
    if not row:
        raise HTTPException(409, 'Chiedi all’ufficio di collegare il tuo account al personale / Demandez au bureau de relier votre compte au personnel')
    return row


def full_name(row):
    return f'{row.nome} {row.cognome}'.strip()


def event(db, user, action, request_id=None, **details):
    db.add(PersonnelEvent(actor_id=user.id, request_id=request_id, action=action,
        details=json.dumps(details, ensure_ascii=False, default=str), created_at=datetime.utcnow()))


def notify_office(db, row, message):
    for user in db.query(User).filter(User.is_active.is_(True)).all():
        if office(user):
            create_notification(db, 'personnel_request', message, recipient_user_id=user.id,
                target_url=f'/manager/personale/richieste?request_id={row.id}')


def cipher():
    from auth import SECRET_KEY
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('personnel-documents-v1:'+SECRET_KEY).encode()).digest()))


def store_attachment(db, row, data):
    if row.kind != 'absence' or row.reason != 'sickness':
        raise HTTPException(422, 'Allegato previsto solo per malattia / Pièce jointe uniquement pour maladie')
    if not data or len(data) > MAX_ATTACHMENT:
        raise HTTPException(422, 'Allegato vuoto o superiore a 5 MB / Pièce jointe vide ou supérieure à 5 Mo')
    mime = 'application/pdf' if data.startswith(b'%PDF-') else 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else None
    if not mime:
        raise HTTPException(422, 'Usa un PDF, JPG o PNG / Utilisez un PDF, JPG ou PNG')
    existing = db.query(PersonnelAttachment).filter_by(request_id=row.id).first()
    if existing:
        raise HTTPException(409, 'Un certificato è già allegato; contatta l’ufficio / Un certificat est déjà joint; contactez le bureau')
    db.add(PersonnelAttachment(request_id=row.id, content_type=mime, encrypted_data=cipher().encrypt(data)))


def create_request(db, user, data, attachment=None):
    target = person(db, data.person_id, True) if data.person_id and office(user) else own_person(db, user)
    if data.person_id and data.person_id != target.id:
        raise HTTPException(403, 'Puoi inviare solo le tue comunicazioni / Vous ne pouvez envoyer que vos communications')
    person(db, target.id, True)
    duplicate = db.query(PersonnelRequest).filter_by(created_by_id=user.id, submission_key=data.submission_key).first()
    if duplicate:
        return duplicate
    if data.end_date and data.end_date < data.start_date or data.end_date and (data.end_date-data.start_date).days > 366:
        raise HTTPException(422, 'Intervallo date non valido (massimo un anno) / Dates invalides (un an maximum)')
    if data.kind in ('leave', 'correction') and not data.end_date:
        raise HTTPException(422, 'Indica la data finale / Indiquez la date de fin')
    if data.kind == 'absence' and data.reason not in ('sickness', 'personal', 'other'):
        raise HTTPException(422, 'Indica il motivo / Indiquez le motif')
    if data.kind == 'correction' and not data.note.strip():
        raise HTTPException(422, 'Descrivi la correzione richiesta / Décrivez la correction demandée')
    row = PersonnelRequest(person_id=target.id, created_by_id=user.id, submission_key=data.submission_key,
        kind=data.kind, reason=data.reason if data.kind == 'absence' else None, start_date=data.start_date,
        end_date=data.end_date, note=data.note.strip(), status='reported' if data.kind == 'absence' else 'pending')
    db.add(row); db.flush()
    if attachment:
        store_attachment(db, row, attachment)
    event(db, user, 'created', row.id, kind=row.kind, on_behalf=user.id != target.user_id)
    notify_office(db, row, f'{full_name(target)} · Nuova comunicazione personale / Nouvelle communication')
    return row


def unavailable(db, person_id, day):
    return db.query(PersonnelRequest).filter(PersonnelRequest.person_id == person_id,
        PersonnelRequest.start_date <= day, or_(PersonnelRequest.end_date.is_(None), PersonnelRequest.end_date >= day),
        or_((PersonnelRequest.kind == 'leave') & (PersonnelRequest.status == 'approved'),
            (PersonnelRequest.kind == 'absence') & PersonnelRequest.status.in_(['reported', 'acknowledged']))).first()


def attendance_snapshot(row):
    return json.dumps([str(row.attendance_date), row.personale_id, row.status, row.site_id, row.hours, row.note, row.report_id])


def sync_request_attendance(db, row):
    """Replace only rows owned by this communication; unrelated history is never overwritten."""
    links = db.query(PersonnelAttendanceLink).filter_by(request_id=row.id).all()
    owned = {link.attendance_id: link for link in links}
    old_rows = {p.id: p for p in db.query(PersonalePresenza).filter(PersonalePresenza.id.in_(owned)).all()}
    for ident, link in owned.items():
        if ident not in old_rows or attendance_snapshot(old_rows[ident]) != link.snapshot:
            raise HTTPException(409, 'Presenze modificate: occorre una verifica dell’ufficio / Présences modifiées : vérification nécessaire')
    days = []
    if row.classification and row.end_date and row.status in ('approved', 'acknowledged'):
        cursor = row.start_date
        while cursor <= row.end_date:
            if row.include_weekends or cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
    existing = db.query(PersonalePresenza).filter(PersonalePresenza.personale_id == row.person_id,
        PersonalePresenza.attendance_date.in_(days)).all()
    conflicts = [p for p in existing if p.id not in owned]
    if conflicts:
        dates = ', '.join(p.attendance_date.strftime('%d/%m/%Y') for p in conflicts[:10])
        raise HTTPException(409, f'Presenze già registrate: {dates}. Verifica il registro prima di procedere / Présences déjà enregistrées : vérifier le registre')
    for link in links:
        db.delete(link)
    db.flush()
    for attendance in old_rows.values():
        db.delete(attendance)
    db.flush()
    for day in days:
        attendance = PersonalePresenza(personale_id=row.person_id, attendance_date=day,
            status=row.classification, hours=None, note=None)
        db.add(attendance); db.flush()
        db.add(PersonnelAttendanceLink(request_id=row.id, attendance_id=attendance.id, snapshot=attendance_snapshot(attendance)))


def decide(db, user, row, data):
    require_office(user)
    person(db, row.person_id, True)
    db.refresh(row, with_for_update=True)
    if row.version != data.version:
        raise HTTPException(409, 'Comunicazione aggiornata: ricarica la pagina / Communication modifiée : rechargez la page')
    allowed = {'leave': {'approved', 'rejected', 'cancelled'}, 'absence': {'acknowledged', 'cancelled'},
        'correction': {'acknowledged', 'closed', 'rejected'}}
    if data.status not in allowed[row.kind] or data.classification and data.classification not in CLASSIFICATIONS:
        raise HTTPException(422, 'Esito o classificazione non valido / Décision ou catégorie invalide')
    if data.end_date and (data.end_date < row.start_date or (data.end_date-row.start_date).days > 366):
        raise HTTPException(422, 'Data finale non valida / Date de fin invalide')
    if data.status in ('rejected', 'cancelled') and not data.response.strip():
        raise HTTPException(422, 'Spiega l’esito alla persona / Expliquez la décision à la personne')
    row.status = data.status
    row.classification = data.classification if row.kind != 'correction' and row.status in ('approved', 'acknowledged') else None
    row.end_date = data.end_date
    if row.kind == 'leave' and row.end_date is None:
        raise HTTPException(422, 'Indica la data finale / Indiquez la date de fin')
    row.include_weekends = data.include_weekends
    row.original_received = data.original_received
    row.response = data.response.strip(); row.office_note = data.office_note.strip()
    sync_request_attendance(db, row)
    row.version += 1
    event(db, user, 'decision', row.id, status=row.status, classification=row.classification,
        end_date=row.end_date, version=row.version, original_received=row.original_received)
    target = db.get(Personale, row.person_id)
    if target.user_id:
        create_notification(db, 'personnel_response', 'L’ufficio ha aggiornato la tua comunicazione / Le bureau a répondu',
            recipient_user_id=target.user_id, target_url=f'/mio-spazio?tab=requests&request_id={row.id}')
    return row


def protect_attendance(db, person_id, day, report_id=None):
    person(db, person_id, True)
    attendance = db.query(PersonalePresenza).filter_by(personale_id=person_id, attendance_date=day).first()
    if attendance and db.query(PersonnelAttendanceLink).filter_by(attendance_id=attendance.id).first():
        raise HTTPException(409, 'Giornata gestita da una comunicazione: modifica l’esito in Richieste / Journée liée à une communication : modifier sa décision')
    if unavailable(db, person_id, day):
        raise HTTPException(409, 'Indisponibilità segnalata: chiedi all’ufficio di verificare / Indisponibilité signalée : contactez le bureau')
    if attendance and attendance.report_id and attendance.report_id != report_id:
        raise HTTPException(409, 'Ore già collegate a un rapportino: correggi il rapportino / Heures liées à un rapport : corrigez le rapport')


def assignments_on(db, day, person_id=None, team_id=None):
    query = db.query(PersonnelAssignment).join(PersonnelTeam).filter(PersonnelAssignment.start_date <= day,
        or_(PersonnelAssignment.end_date.is_(None), PersonnelAssignment.end_date >= day), PersonnelTeam.active.is_(True))
    if person_id: query = query.filter(PersonnelAssignment.person_id == person_id)
    if team_id: query = query.filter(PersonnelAssignment.team_id == team_id)
    return query.all()


def team_label(db, team):
    destination = db.get(Site, team.site_id) if team.site_id else db.get(Depot, team.depot_id)
    return destination.name if destination else team.name


def save_team(db, user, data):
    require_office(user)
    if not data.name.strip():
        raise HTTPException(422, 'Indica il nome della squadra / Indiquez le nom de l’équipe')
    lead = db.get(User, data.lead_id)
    if not lead or not lead.is_active or not user_has_role(lead, RoleEnum.caposquadra):
        raise HTTPException(422, 'Seleziona un caposquadra attivo / Sélectionnez un chef d’équipe actif')
    if bool(data.site_id) == bool(data.depot_id):
        raise HTTPException(422, 'Scegli un cantiere oppure un deposito / Choisissez un chantier ou un dépôt')
    destination = db.query(Site if data.site_id else Depot).filter_by(id=data.site_id or data.depot_id).with_for_update().first()
    if not destination or not destination.is_active:
        raise HTTPException(422, 'Destinazione non attiva / Destination inactive')
    if data.site_id and db.query(PersonnelTeam).filter_by(site_id=data.site_id).first():
        raise HTTPException(409, 'Il cantiere ha già una squadra / Le chantier a déjà une équipe')
    row = PersonnelTeam(name=data.name.strip(), lead_id=lead.id, site_id=data.site_id, depot_id=data.depot_id)
    if data.site_id:
        # Existing site authorization remains the source of operational permissions.
        if destination.caposquadra_id and destination.caposquadra_id != lead.id:
            raise HTTPException(409, 'Il caposquadra deve corrispondere al responsabile del cantiere. Aggiornalo prima nel cantiere / Mettez d’abord à jour le responsable du chantier')
        destination.caposquadra_id = lead.id
    db.add(row); db.flush()
    event(db, user, 'team_created', team_id=row.id, lead_id=lead.id)
    return row


def team_lead(db, team):
    site = db.get(Site, team.site_id) if team.site_id else None
    return db.get(User, site.caposquadra_id if site and site.caposquadra_id else team.lead_id)


def effective_roster(db, site_id, day):
    """Daily planning overrides the baseline team, without changing membership."""
    from models import ResourcePlan
    plans = db.query(ResourcePlan).filter_by(day=day, resource_type='person').all()
    overrides = {p.resource_id: p for p in plans}
    team = db.query(PersonnelTeam).filter_by(site_id=site_id, active=True).first()
    members = {a.person_id for a in assignments_on(db, day, team_id=team.id)} if team else set()
    members = {ident for ident in members if ident not in overrides or overrides[ident].site_id == site_id}
    members.update(p.resource_id for p in plans if p.site_id == site_id)
    return team, db.query(Personale).filter(Personale.id.in_(members), Personale.attivo.is_(True)).order_by(Personale.cognome, Personale.nome).all()


def assign(db, user, team_id, data):
    require_office(user)
    row = person(db, data.person_id, True)
    team = db.get(PersonnelTeam, team_id)
    if not team or not team.active:
        raise HTTPException(404, 'Squadra non trovata / Équipe introuvable')
    if data.end_date and data.end_date < data.start_date:
        raise HTTPException(422, 'Intervallo non valido / Dates invalides')
    conflict = db.query(PersonnelAssignment).filter(PersonnelAssignment.person_id == row.id,
        PersonnelAssignment.start_date <= (data.end_date or date.max),
        or_(PersonnelAssignment.end_date.is_(None), PersonnelAssignment.end_date >= data.start_date)).first()
    if conflict:
        raise HTTPException(409, 'La persona è già assegnata nel periodo. Termina prima l’assegnazione precedente / La personne est déjà affectée sur cette période')
    assignment = PersonnelAssignment(team_id=team_id, person_id=row.id, start_date=data.start_date, end_date=data.end_date)
    db.add(assignment); db.flush()
    event(db, user, 'assigned', assignment_id=assignment.id, person_id=row.id, team_id=team_id,
        start=data.start_date, end=data.end_date)
    if row.user_id:
        create_notification(db, 'personnel_assignment', f'Nuova assegnazione / Nouvelle affectation · {team_label(db, team)}',
            recipient_user_id=row.user_id, target_url='/mio-spazio?tab=sites')
    return assignment
