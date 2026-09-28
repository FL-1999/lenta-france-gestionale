import re
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from models import ProjectPartner, ProjectPartnerSite, Site
from audit_utils import log_audit_event

Category = Literal['moe', 'moa', 'gros_oeuvre', 'terrassement', 'other']
CATEGORIES = {
    'moe': ('Maîtrise d’œuvre · Direzione lavori', 'Maîtrise d’œuvre'),
    'moa': ('Maîtrise d’ouvrage · Committente', 'Maîtrise d’ouvrage'),
    'gros_oeuvre': ('Gros œuvre · Impresa strutture', 'Gros œuvre'),
    'terrassement': ('Terrassement · Movimento terra', 'Terrassement'),
    'other': ('Altro', 'Autre'),
}


class ProjectLink(BaseModel):
    site_id: int = Field(gt=0)
    roles: list[Category] = Field(min_length=1, max_length=5)


class PartnerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: int | None = Field(default=None, gt=0)
    revision: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=255)
    categories: list[Category] = Field(min_length=1, max_length=5)
    contact_name: str = Field(default='', max_length=255)
    email: str = Field(default='', max_length=255)
    phone: str = Field(default='', max_length=100)
    address: str = Field(default='', max_length=255)
    city: str = Field(default='', max_length=120)
    country: str = Field(default='', max_length=120)
    vat_number: str = Field(default='', max_length=100)
    notes: str = Field(default='', max_length=4000)
    active: bool = True
    projects: list[ProjectLink] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def coherent(self):
        if self.email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.email):
            raise ValueError('Controlla l’email / Vérifiez l’adresse e-mail')
        if len({p.site_id for p in self.projects}) != len(self.projects):
            raise ValueError('Cantiere ripetuto: seleziona più ruoli sulla stessa riga / Chantier répété : sélectionnez plusieurs rôles sur la même ligne')
        return self


def site_snapshot(site):
    return dict(name=site.name, code=site.code or '', city=site.city or '',
                status=getattr(site.status, 'value', site.status),
                start=str(site.start_date or ''), end=str(site.end_date or ''))


def partner_row(db, pid):
    row = db.query(ProjectPartner).options(selectinload(ProjectPartner.projects).selectinload(ProjectPartnerSite.site)).filter_by(id=pid).first()
    if not row:
        raise HTTPException(404, 'Scheda non trovata / Fiche introuvable')
    return row


def serialize(row):
    return dict(**row.payload, id=row.id, revision=row.revision, active=row.active,
                projects=[dict(site_id=p.site_id, roles=p.roles,
                               **(site_snapshot(p.site) if p.site else p.snapshot))
                          for p in sorted(row.projects, key=lambda p: p.id)])


def save(db, body, user):
    # Validation is separate from supplier-service fields.
    from pydantic import ValidationError
    try:
        value = PartnerInput.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(400, [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()])
    # Lock sites first, matching site deletion's lock order.
    sites = {s.id: s for s in db.query(Site).filter(Site.id.in_([p.site_id for p in value.projects])).order_by(Site.id).with_for_update()}
    if len(sites) != len(value.projects):
        raise HTTPException(400, 'Un cantiere non è più disponibile. Controlla i collegamenti. / Un chantier n’est plus disponible. Vérifiez les associations.')
    row = None
    before = None
    if value.id:
        row = db.query(ProjectPartner).filter_by(id=value.id).with_for_update().first()
        if not row:
            raise HTTPException(404)
        if row.revision != value.revision:
            raise HTTPException(409, 'Scheda modificata da un altro utente. Ricarica. / Fiche modifiée par un autre utilisateur. Actualisez.')
        before = serialize(row)
    key = ' '.join(value.name.casefold().split())
    duplicate = db.query(ProjectPartner).filter_by(name_key=key).first()
    if duplicate and (not row or duplicate.id != row.id):
        raise HTTPException(409, 'Nome già presente nella rubrica, anche tra gli archiviati. / Nom déjà présent dans l’annuaire, y compris dans les archives.')
    if not row:
        row = ProjectPartner(); db.add(row)
    else:
        row.revision += 1
    row.name, row.name_key, row.active = value.name, key, value.active
    row.payload = value.model_dump(exclude={'id', 'revision', 'active', 'projects'})
    existing = {p.site_id: p for p in row.projects if p.site_id}
    wanted = {p.site_id for p in value.projects}
    for sid, link in existing.items():
        if sid not in wanted:
            row.projects.remove(link)
    for p in value.projects:
        link = existing.get(p.site_id)
        if not link:
            link = ProjectPartnerSite(site_id=p.site_id); row.projects.append(link)
        link.roles = list(dict.fromkeys(p.roles))
        link.snapshot = site_snapshot(sites[p.site_id])
    # Deleted-site snapshots remain in history, even when the contact is edited.
    db.flush()
    log_audit_event(db, user, 'PROJECT_PARTNER_SAVED', 'project_partner', row.id,
                    {'before': before, 'after': serialize(row)})
    return row


def for_site(db, sid):
    return [dict(id=p.partner.id, name=p.partner.name, roles=p.roles, active=p.partner.active)
            for p in db.query(ProjectPartnerSite).options(selectinload(ProjectPartnerSite.partner)).filter_by(site_id=sid).order_by(ProjectPartnerSite.id)]
