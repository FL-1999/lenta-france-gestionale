import pytest
from fastapi import HTTPException
from models import User, RoleEnum, AuditLog, Notification, AccountRevocation, Fiche
from services.user_deletion import delete_account
from auth import create_access_token, create_refresh_token, decode_access_token, decode_refresh_token, token_is_revoked
from test_operations import operations


def prepare(o):
    db=o['db'];o['manager'].role=RoleEnum.admin;o['actor'][0]=o['manager']
    target=User(email='delete-me@example.com',full_name='Profilo prova',role=RoleEnum.driver,hashed_password='unused',is_active=True)
    db.add(target);db.commit()
    return target, f'/manager/utenti/{target.id}/elimina'


def test_admin_delete_confirmation_audit_and_notification_cleanup(operations):
    o=operations;db=o['db'];target,path=prepare(o);uid=target.id;email=target.email;c=o['client']
    db.add(AuditLog(user_id=uid,action='TEST',target_type='user',target_id=uid,extra_data={'kept':True}))
    db.add(Notification(recipient_user_id=uid,notification_type='test',message='Private notification'));db.commit()
    assert c.get(path).status_code==200
    assert c.post(path,data={'conferma_email':'wrong@example.com'}).status_code==400
    assert db.query(User).filter_by(id=uid).count()==1
    assert c.post(path,data={'conferma_email':email},headers={'Origin':'https://other.example'}).status_code==403
    r=c.post(path,data={'conferma_email':email},follow_redirects=False);assert r.status_code==303,r.text
    assert db.query(User).filter_by(id=uid).count()==0
    assert db.query(Notification).filter_by(recipient_user_id=uid).count()==0
    a=db.query(AuditLog).filter_by(action='TEST').one();assert a.user_id is None and a.extra_data['kept']
    assert a.extra_data['deleted_actor']['email']==email
    assert db.query(AuditLog).filter_by(action='USER_DELETED').count()==1
    assert db.get(AccountRevocation,email) is not None
    assert c.post(path,data={'conferma_email':email}).status_code==404


def test_non_admin_and_self_are_protected(operations):
    o=operations;target,path=prepare(o);c=o['client']
    o['actor'][0]=o['capo']
    assert c.get(path).status_code==403
    assert c.post(path,data={'conferma_email':target.email}).status_code==403
    o['actor'][0]=o['manager'];o['manager'].role=RoleEnum.manager;o['db'].commit()
    assert c.post(path,data={'conferma_email':target.email}).status_code==403
    o['manager'].role=RoleEnum.admin;o['db'].commit()
    assert c.post(f'/manager/utenti/{o["manager"].id}/elimina',data={'conferma_email':o['manager'].email}).status_code==400


def test_business_history_is_never_cascaded(operations):
    o=operations;target,path=prepare(o);db=o['db'];c=o['client']
    from test_site_pours import setup, fiche
    setup(o);assert fiche(o,1,10).status_code==303
    f=db.query(Fiche).one();f.created_by_id=target.id;db.commit()
    assert 'Fiches' in c.get(path).text
    assert c.post(path,data={'conferma_email':target.email}).status_code==409
    assert db.query(Fiche).count()==1 and db.query(User).filter_by(id=target.id).count()==1


def test_last_admin_and_personnel_links_are_protected(operations):
    o=operations;target,path=prepare(o);db=o['db']
    target.role=RoleEnum.admin;o['manager'].role=RoleEnum.manager;db.commit()
    with pytest.raises(HTTPException,match='amministratore'):
        delete_account(db,o['manager'],target.id,target.email)
    db.rollback();o['manager'].role=RoleEnum.admin;o['person'].user_id=target.id;db.commit()
    assert o['client'].post(path,data={'conferma_email':target.email}).status_code==409


def test_deleted_email_cannot_reuse_old_sessions(operations):
    o=operations;target,path=prepare(o);db=o['db'];email=target.email
    old_access=create_access_token({'sub':email});old_refresh=create_refresh_token(email)
    assert o['client'].post(path,data={'conferma_email':email},follow_redirects=False).status_code==303
    db.add(User(email=email,role=RoleEnum.driver,hashed_password='new',is_active=True));db.commit()
    assert token_is_revoked(db,decode_access_token(old_access))
    assert token_is_revoked(db,{'sub':email})  # legacy tokens without issued-at
    assert decode_refresh_token(old_refresh,db=db) is None
    assert not token_is_revoked(db,decode_access_token(create_access_token({'sub':email})))
    assert decode_refresh_token(create_refresh_token(email),db=db)==email
    import main
    assert main._mint_access_token_for_email(email,old_refresh) is None


def test_deleted_bootstrap_account_is_not_recreated(operations, monkeypatch):
    import main
    o=operations;target,path=prepare(o);email=target.email
    assert o['client'].post(path,data={'conferma_email':email},follow_redirects=False).status_code==303
    monkeypatch.setattr(main,'ADMIN_EMAIL',email);monkeypatch.setattr(main,'ADMIN_PASSWORD','bootstrap-example')
    main.create_initial_admin()
    assert o['db'].query(User).filter_by(email=email).count()==0
