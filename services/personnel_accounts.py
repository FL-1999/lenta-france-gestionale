"""Admin-only account provisioning from an existing personnel record."""
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from auth import hash_password
from models import Personale, User, Role, UserRole, RoleEnum, Site, PersonnelTeam
from permissions import get_user_roles, has_perm
from services import personnel as svc

SIMPLE_ROLES = {RoleEnum.personale, RoleEnum.caposquadra}


def require_admin(user):
    if not user or not user.is_active or not has_perm(user, 'users.manage'):
        raise HTTPException(403, 'Operazione riservata all’admin / Opération réservée à l’admin')


def editable_account(user):
    return bool(user and user.is_active and set(get_user_roles(user)) <= SIMPLE_ROLES
                and not user.can_switch_roles)


def account_snapshot(user):
    import hashlib
    import json
    return hashlib.sha256(json.dumps([user.id, user.role.value, sorted(r.value for r in get_user_roles(user)),
        user.is_active, user.can_switch_roles, user.email]).encode()).hexdigest()


def set_single_role(db, user, value):
    role = db.query(Role).filter_by(name=value).first()
    if not role:
        role = Role(name=value)
        db.add(role)
        db.flush()
    for link in list(user.user_roles):
        db.delete(link)
    db.flush()
    user.user_roles = [UserRole(role=role)]
    user.role = value
    user.can_switch_roles = False


def create_account(db, actor, person_id, data):
    require_admin(actor)
    row = svc.person(db, person_id, True)
    if row.user_id:
        raise HTTPException(409, 'Questa persona ha già un accesso collegato. Ricarica la scheda. / Cette personne a déjà un compte lié.')
    email = str(data.email).strip().lower()
    if db.query(User.id).filter(func.lower(User.email) == email).first():
        raise HTTPException(409, 'Email già utilizzata: scegli Collega un account esistente. / Email déjà utilisée : reliez le compte existant.')
    account = User(email=email, full_name=svc.full_name(row), hashed_password=hash_password(data.password),
        role=RoleEnum(data.role), language=data.language, is_active=True, can_switch_roles=False)
    db.add(account)
    try:
        db.flush()
        set_single_role(db, account, RoleEnum(data.role))
        row.user_id = account.id
        svc.event(db, actor, 'account_created_and_linked', person_id=row.id, user_id=account.id, role=data.role)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Account già presente: ricarica la scheda e verifica il collegamento. / Compte déjà présent : rechargez la fiche.')
    return {'ok': True}


def change_access(db, actor, person_id, data):
    require_admin(actor)
    account = db.query(User).filter_by(id=data.user_id).with_for_update().first()
    row = svc.person(db, person_id, True)
    if not account or row.user_id != account.id or account_snapshot(account) != data.expected:
        raise HTTPException(409, 'Accesso modificato: ricarica la scheda / Compte modifié : rechargez la fiche')
    if not editable_account(account):
        raise HTTPException(409, 'Questo account ha permessi specifici: gestiscilo in Utenti. / Gérez les permissions spécifiques dans Utilisateurs.')
    role = RoleEnum(data.role)
    if role == RoleEnum.personale and (
        db.query(Site.id).filter_by(caposquadra_id=account.id, is_active=True).first()
        or db.query(PersonnelTeam.id).filter_by(lead_id=account.id, active=True).first()
    ):
        raise HTTPException(409, 'Prima assegna un altro caposquadra ai cantieri e alle squadre di questa persona. / Affectez d’abord un autre responsable aux chantiers et équipes.')
    before = account.role.value
    set_single_role(db, account, role)
    svc.event(db, actor, 'account_role_changed', person_id=row.id, user_id=account.id, before=before, after=role.value)
    db.commit()
    return {'ok': True}
