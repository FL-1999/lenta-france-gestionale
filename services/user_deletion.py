import time
from sqlalchemy import select, func, delete
from sqlmodel import SQLModel
from fastapi import HTTPException
from models import Base, User, RoleEnum, Personale, AuditLog, Notification, UserRole
from models.account_revocation import AccountRevocation
from permissions import user_has_role
from audit_utils import log_audit_event


ACCOUNT_TABLES = {'user_roles', 'notifications', 'audit_logs'}
LABELS = {'sites':'Cantieri assegnati', 'reports':'Rapportini', 'fiches':'Fiches',
          'report_drafts':'Bozze rapportini', 'site_tasks':'Attività',
          'purchase_orders':'Ordini', 'resource_plans':'Pianificazione',
          'site_documents':'Documenti', 'site_plans':'Piante',
          'magazzino_movimenti':'Movimenti magazzino'}


def references(db, user_id):
    """Fail closed for every business FK, including future models and delete cascades."""
    result=[]; seen=set()
    for metadata in (Base.metadata, SQLModel.metadata):
        for table in metadata.tables.values():
            if table.name in seen or table.name in ACCOUNT_TABLES: continue
            seen.add(table.name)
            cols=[c for c in table.columns if any(f.target_fullname=='users.id' for f in c.foreign_keys)]
            if cols:
                from sqlalchemy import or_
                count=db.scalar(select(func.count()).select_from(table).where(or_(*(c==user_id for c in cols))))
                if count: result.append({'label':LABELS.get(table.name,'Dati collegati: '+table.name), 'count':count})
    # Personale deliberately has no database FK; it still owns hours and assignments.
    count=db.query(Personale).filter(Personale.user_id==user_id).count()
    if count: result.append({'label':'Schede personale e relativo storico','count':count})
    return result


def delete_account(db, actor, target_id, confirmation):
    # Serialize concurrent admin deletions and hold the target against new FK references.
    users=db.query(User).order_by(User.id).with_for_update().all()
    target=next((u for u in users if u.id==target_id),None)
    if target is None: raise HTTPException(404,'Profilo non trovato.')
    if target.id==actor.id: raise HTTPException(400,'Non puoi eliminare il profilo con cui sei collegato.')
    if confirmation.strip().casefold()!=target.email.casefold():
        raise HTTPException(400,'Scrivi l’email esatta del profilo per confermare.')
    if target.is_active and user_has_role(target,RoleEnum.admin) and not any(
        u.id!=target.id and u.is_active and user_has_role(u,RoleEnum.admin) for u in users):
        raise HTTPException(400,'Deve rimanere almeno un amministratore attivo.')
    if references(db,target.id):
        raise HTTPException(409,'Il profilo ha dati di lavoro collegati. Disattivalo per conservare lo storico.')
    identity={'id':target.id,'email':target.email,'full_name':target.full_name,'roles':target.assigned_role_values}
    for entry in db.query(AuditLog).filter_by(user_id=target.id):
        details=entry.extra_data
        entry.extra_data={**(details if isinstance(details,dict) else {'previous_details':details}), 'deleted_actor':identity}
        entry.user_id=None
    revocation=db.get(AccountRevocation,target.email)
    if not revocation: revocation=AccountRevocation(email=target.email);db.add(revocation)
    revocation.revoked_at=time.time()
    db.flush()
    db.execute(delete(Notification).where(Notification.recipient_user_id==target.id))
    db.execute(delete(UserRole).where(UserRole.user_id==target.id))
    # Core deletion intentionally avoids User.reports/fiches ORM delete-orphan cascades.
    db.execute(delete(User.__table__).where(User.id==target.id))
    log_audit_event(db,actor,'USER_DELETED','user',target.id,identity)
