"""Notebook authorization and versioned writes, independent of business permissions."""
from datetime import datetime
from typing import Annotated, Literal
import copy
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select, update
from models import (NotebookNote, NotebookGrant, NotebookRevision, NotebookDraft, NotebookExtract,
                    User, Site, Personale, PersonnelTeam, PersonnelAssignment, ResourcePlan)
from permissions import has_perm
from notifications import create_notification
from audit_utils import log_audit_event

Short = Annotated[str, Field(max_length=1000)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Action(StrictInput):
    text: str = Field(min_length=1, max_length=1000)
    assignee: str = Field('', max_length=150)
    due: str = Field('', max_length=100)
    done: bool = False


class Details(StrictInput):
    when: str = Field('', max_length=100)
    attendees: list[Short] = Field(default_factory=list, max_length=50)
    agenda: list[Short] = Field(default_factory=list, max_length=100)
    decisions: list[Short] = Field(default_factory=list, max_length=100)
    actions: list[Action] = Field(default_factory=list, max_length=100)


class Content(StrictInput):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal['free', 'meeting', 'list'] = 'free'
    body: str = Field('', max_length=30000)
    details: Details = Field(default_factory=Details)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Indica un titolo / Indiquez un titre')
        return value.strip()


class Create(Content):
    request_key: str = Field(min_length=16, max_length=64, pattern=r'^[a-zA-Z0-9-]+$')
    site_id: int | None = Field(None, gt=0)
    collection: str = Field('', max_length=100)


class Edit(Content):
    version: int = Field(ge=1)
    site_id: int | None = Field(None, gt=0)
    collection: str = Field('', max_length=100)


class Version(StrictInput):
    version: int = Field(ge=1)


class GrantInput(StrictInput):
    user_id: int = Field(gt=0)
    permission: Literal['read', 'edit']


class Sharing(Version):
    grants: list[GrantInput] = Field(max_length=100)
    confirm: Literal[True]


class Archive(Version):
    archived: bool


def visible_query(db, user):
    shared = select(NotebookGrant.note_id).where(NotebookGrant.user_id == user.id)
    return db.query(NotebookNote).filter(or_(NotebookNote.owner_id == user.id, NotebookNote.id.in_(shared)))


def find(db, ident, user, *, owner=False, edit=False):
    row = visible_query(db, user).filter(NotebookNote.id == ident).populate_existing().first()
    if not row:
        raise HTTPException(404, 'Appunto non trovato / Note introuvable')
    if row.owner_id != user.id:
        grant = db.query(NotebookGrant).filter_by(note_id=ident, user_id=user.id).first()
        if owner or edit and (not grant or grant.permission != 'edit'):
            raise HTTPException(403, 'Operazione riservata al proprietario / Opération réservée au propriétaire')
    if edit and row.archived:
        raise HTTPException(409, 'Ripristina l’appunto prima di modificarlo / Restaurez la note avant de la modifier')
    return row


def assigned_site_ids(db, user):
    if has_perm(user, 'manager.access'):
        return select(Site.id)
    ids = set(db.scalars(select(Site.id).where(Site.caposquadra_id == user.id)))
    person = db.query(Personale).filter_by(user_id=user.id, attivo=True).first()
    if person:
        from services.personnel import today
        day = today()
        ids.update(db.scalars(select(PersonnelTeam.site_id).join(PersonnelAssignment,
            PersonnelAssignment.team_id == PersonnelTeam.id).where(
            PersonnelAssignment.person_id == person.id, PersonnelTeam.active.is_(True),
            PersonnelTeam.site_id.isnot(None), PersonnelAssignment.start_date <= day,
            or_(PersonnelAssignment.end_date.is_(None), PersonnelAssignment.end_date >= day))))
        ids.update(db.scalars(select(ResourcePlan.site_id).where(ResourcePlan.resource_type == 'person',
            ResourcePlan.resource_id == person.id, ResourcePlan.day == day)))
    return list(ids)


def sites(db, user):
    # Historical personal notes and explicit shares retain their contextual label.
    linked = visible_query(db, user).with_entities(NotebookNote.site_id)
    return db.query(Site).filter(or_(Site.id.in_(assigned_site_ids(db, user)),
        Site.id.in_(linked))).order_by(Site.name).all()


def assignable_sites(db, user):
    return db.query(Site).filter(Site.id.in_(assigned_site_ids(db, user))).order_by(Site.name).all()


def require_site(db, user, site_id):
    if site_id is not None and not db.query(Site.id).filter(
        Site.id == site_id, Site.id.in_(assigned_site_ids(db, user))).first():
        raise HTTPException(403, 'Cantiere non assegnato / Chantier non affecté')


def snapshot(row):
    return {k: copy.deepcopy(getattr(row, k)) for k in ('title', 'kind', 'body', 'details')}


def version_write(db, row, expected, user, changes, *, preserve=False):
    if row.version != expected:
        raise HTTPException(409, 'Appunto modificato: ricarica prima di salvare / Note modifiée : rechargez avant d’enregistrer')
    before = snapshot(row)
    old_version = row.version
    changed = db.execute(update(NotebookNote).where(NotebookNote.id == row.id,
        NotebookNote.version == expected).values(**changes, version=expected + 1,
        updated_at=datetime.utcnow()), execution_options={'synchronize_session': False}).rowcount
    if not changed:
        db.rollback()
        raise HTTPException(409, 'Appunto modificato: ricarica prima di salvare / Note modifiée : rechargez avant d’enregistrer')
    if preserve:
        db.add(NotebookRevision(note_id=row.id, actor_id=user.id, version=old_version, content=before))
    db.expire(row)
    return row


def data(db, row, user, *, full=False):
    owner = row.owner_id == user.id
    author = db.get(User, row.owner_id)
    grants = db.query(NotebookGrant).filter_by(note_id=row.id).all()
    mine = next((g for g in grants if g.user_id == user.id), None)
    site = db.get(Site, row.site_id) if row.site_id else None
    result = dict(id=row.id, title=row.title, kind=row.kind, owner=owner,
        author=author.full_name or author.email, site_id=row.site_id,
        site=site.name if site else (row.site_snapshot or {}).get('name'),
        site_code=site.code if site else (row.site_snapshot or {}).get('code'),
        collection=row.collection if owner else '', archived=row.archived,
        version=row.version, created_at=row.created_at, updated_at=row.updated_at,
        shared=bool(grants), can_edit=bool(owner or mine and mine.permission == 'edit') and not row.archived)
    if full:
        result.update(body=row.body, details=row.details, grants=[
            dict(user_id=g.user_id, permission=g.permission,
                 name=(db.get(User, g.user_id).full_name or db.get(User, g.user_id).email),
                 active=db.get(User, g.user_id).is_active) for g in grants] if owner else [])
        if owner:
            draft = db.query(NotebookDraft).filter_by(note_id=row.id, state='ready',
                base_version=row.version).order_by(NotebookDraft.created_at.desc()).first()
            result['draft'] = dict(id=draft.id, result=draft.result, mode=draft.mode) if draft else None
            # Never expose titles or even IDs of the complete meeting through a shared extract.
            source = db.query(NotebookNote).join(NotebookExtract,
                NotebookExtract.source_note_id == NotebookNote.id).filter(
                NotebookExtract.child_note_id == row.id, NotebookNote.owner_id == user.id).first()
            extracts = db.query(NotebookNote).join(NotebookExtract,
                NotebookExtract.child_note_id == NotebookNote.id).filter(
                NotebookExtract.source_note_id == row.id, NotebookNote.owner_id == user.id).order_by(NotebookExtract.id).all()
            result['source_note'] = dict(id=source.id, title=source.title) if source else None
            result['extracts'] = [dict(id=n.id, title=n.title, archived=n.archived) for n in extracts]
    return result


def create(db, user, payload):
    existing = db.query(NotebookNote).filter_by(owner_id=user.id, request_key=payload.request_key).first()
    if existing:
        return existing
    require_site(db, user, payload.site_id)
    row = NotebookNote(owner_id=user.id, **payload.model_dump())
    db.add(row)
    db.flush()
    log_audit_event(db, user, 'notebook.created', 'notebook', row.id)
    return row


def edit(db, row, user, payload):
    changes = payload.model_dump(exclude={'version'})
    if row.owner_id != user.id:
        if payload.site_id != row.site_id or payload.collection:
            raise HTTPException(403, 'Solo il proprietario può cambiare cantiere e raccolta / Seul le propriétaire peut modifier le classement')
        changes.pop('collection')
    elif payload.site_id != row.site_id:
        require_site(db, user, payload.site_id)
        if db.query(NotebookGrant).filter_by(note_id=row.id).first():
            raise HTTPException(409, 'Rendi privato l’appunto prima di cambiare cantiere / Rendez la note privée avant de changer de chantier')
        changes['site_snapshot'] = {}
    return version_write(db, row, payload.version, user, changes, preserve=True)


def share(db, row, user, payload):
    ids = [g.user_id for g in payload.grants]
    if len(ids) != len(set(ids)) or user.id in ids:
        raise HTTPException(422, 'Destinatari duplicati o non validi / Destinataires invalides')
    targets = db.query(User).filter(User.id.in_(ids), User.is_active.is_(True)).all()
    if len(targets) != len(ids):
        raise HTTPException(422, 'Scegli persone con un account attivo / Choisissez des comptes actifs')
    previous = {g.user_id for g in db.query(NotebookGrant).filter_by(note_id=row.id)}
    version_write(db, row, payload.version, user, {})
    db.query(NotebookGrant).filter_by(note_id=row.id).delete(synchronize_session=False)
    for grant in payload.grants:
        db.add(NotebookGrant(note_id=row.id, **grant.model_dump()))
        if grant.user_id not in previous:
            # No note title/content in notifications: revocation must not leave a snippet behind.
            create_notification(db, 'notebook_shared', 'Un appunto è stato condiviso con te / Une note a été partagée avec vous',
                recipient_user_id=grant.user_id, target_url=f'/appunti?note={row.id}')
    log_audit_event(db, user, 'notebook.sharing_changed', 'notebook', row.id,
        {'grants': [g.model_dump() for g in payload.grants]})
    return row
