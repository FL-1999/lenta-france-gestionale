from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel

import main
from auth import verify_password
from database import get_session, ensure_model_columns
from models import Base, User, RoleEnum, Personale, PersonalePresenza, PersonnelEvent, PersonnelTeam
from permissions import get_user_roles
from routes.personnel import token
from services.personnel_accounts import account_snapshot
from test_operations import operations


@pytest.fixture
def setup(operations):
    o = operations
    admin = User(email='personnel-admin@example.com', full_name='Admin Test', role=RoleEnum.admin, hashed_password='x', is_active=True)
    worker = Personale(nome='Mario', cognome='Personale', ruolo='manovale', attivo=True)
    o['db'].add_all([admin, worker]); o['db'].commit()
    o.update(admin=admin, worker=worker)
    o['actor'][0] = admin
    def session():
        with Session(o['db'].get_bind()) as db:
            yield db
    main.app.dependency_overrides[get_session] = session
    return o


def post(o, path, body, actor=None):
    if actor: o['actor'][0] = actor
    return o['client'].post(path, json=body, headers={'X-CSRF-Token': token(o['actor'][0])})


def create(o, **extra):
    return post(o, f"/manager/personale/{o['worker'].id}/crea-accesso", dict(
        email='worker-access@example.com', password='Only-test-password-2026', role='personale', language='fr', **extra))


def test_create_links_existing_person_without_duplicate_and_password_leak(setup):
    o=setup; db=o['db']; count=db.query(Personale).count()
    result=create(o); assert result.status_code==200
    db.expire_all(); worker=db.get(Personale,o['worker'].id); account=db.get(User,worker.user_id)
    assert db.query(Personale).count()==count and worker.ruolo=='manovale'
    assert account.role==RoleEnum.personale and get_user_roles(account)==(RoleEnum.personale,)
    assert verify_password('Only-test-password-2026',account.hashed_password)
    assert account.language=='fr' and account.is_active
    assert 'Only-test-password' not in result.text
    events=''.join(e.details for e in db.query(PersonnelEvent).all())
    assert 'Only-test-password' not in events and 'hashed_password' not in events
    assert create(o).status_code==409
    assert db.query(User).filter_by(email='worker-access@example.com').count()==1


def test_duplicate_email_is_case_insensitive_and_requires_explicit_link(setup):
    o=setup; db=o['db']
    existing=User(email='WORKER-access@EXAMPLE.com',role=RoleEnum.personale,hashed_password='keep',is_active=True)
    db.add(existing); db.commit()
    assert create(o).status_code==409
    assert db.get(Personale,o['worker'].id).user_id is None
    assert post(o,f"/manager/personale/{o['worker'].id}/account",{'user_id':existing.id}).status_code==200
    assert existing.hashed_password=='keep'
    assert post(o,f"/manager/personale/{o['person'].id}/account",{'user_id':existing.id}).status_code==409


@pytest.mark.parametrize('role',['manager','caposquadra','personale'])
def test_admin_controls_are_hidden_and_endpoints_forbidden(setup,role):
    o=setup; actor=User(email=role+'-no-admin@example.com',role=RoleEnum(role),hashed_password='x',is_active=True)
    o['db'].add(actor);o['db'].commit();o['actor'][0]=actor
    assert create(o).status_code==403
    assert post(o,'/manager/personale/presenze/elenco',{'people':[{'person_id':o['worker'].id,'included':False,'expected':True}]}).status_code==403
    assert post(o,f"/manager/personale/{o['worker'].id}/account",{'user_id':o['admin'].id}).status_code==403
    assert post(o,f"/manager/personale/{o['worker'].id}/tipo-accesso",{'user_id':o['admin'].id,'expected':'a'*64,'role':'personale'}).status_code==403
    if role=='manager':
        html=o['client'].get(f"/manager/personale/{o['worker'].id}/edit")
        assert html.status_code==200 and 'data-admin-action' not in html.text
        assert 'data-admin-action' not in o['client'].get('/manager/personale/presenze').text
        assert o['client'].get('/manager/personale/presenze?show_excluded=true').status_code==403
        o['client'].post(f"/manager/personale/{o['worker'].id}/edit",data={'nome':'Mario','cognome':'Personale','attivo':'true','incluso_presenze':'false','user_id':o['admin'].id})
        o['db'].expire_all()
        assert o['worker'].incluso_presenze and o['worker'].user_id is None


def test_create_requires_csrf_and_cannot_create_privileged_account(setup):
    o=setup; path=f"/manager/personale/{o['worker'].id}/crea-accesso"
    body=dict(email='safe@example.com',password='Only-test-password-2026',role='personale')
    assert o['client'].post(path,json=body).status_code==403
    assert o['client'].post(path,json=body,headers={'X-CSRF-Token':token(o['admin']),'Origin':'https://evil.example.com'}).status_code==403
    assert post(o,path,{**body,'role':'admin'}).status_code==422
    assert post(o,path,{**body,'password':'weak'}).status_code==422
    assert o['worker'].user_id is None


def test_role_change_preserves_person_and_guards_assignments_privileged_and_stale(setup):
    o=setup;db=o['db'];assert create(o).status_code==200
    account=db.get(User,o['worker'].user_id); expected=account_snapshot(account)
    path=f"/manager/personale/{o['worker'].id}/tipo-accesso"
    assert post(o,path,dict(user_id=account.id,expected=expected,role='caposquadra')).status_code==200
    db.expire_all(); assert get_user_roles(account)==(RoleEnum.caposquadra,)
    assert post(o,path,dict(user_id=account.id,expected=expected,role='personale')).status_code==409
    o['site'].caposquadra_id=account.id;db.commit()
    body=dict(user_id=account.id,expected=account_snapshot(account),role='personale')
    assert post(o,path,body).status_code==409
    o['site'].caposquadra_id=o['capo'].id;db.commit()
    assert post(o,path,body).status_code==200
    o['worker'].user_id=o['admin'].id;db.commit()
    assert post(o,path,dict(user_id=o['admin'].id,expected=account_snapshot(o['admin']),role='personale')).status_code==409
    assert o['admin'].role==RoleEnum.admin


def test_visibility_is_per_person_reversible_and_preserves_records(setup):
    o=setup;db=o['db'];worker=o['worker']
    db.add(PersonalePresenza(personale_id=worker.id,attendance_date=date(2026,10,13),status='WORK',hours=7));db.commit()
    url='/manager/personale/presenze/elenco'
    body={'people':[dict(person_id=worker.id,included=False,expected=True)]}
    assert post(o,url,body).status_code==200
    db.expire_all();assert not worker.incluso_presenze and worker.attivo
    assert db.query(PersonalePresenza).one().hours==7
    assert post(o,url,body).status_code==409
    o['actor'][0]=o['manager']
    for query in ['?week_start=2026-10-12','?view=month&month=2026-10&report_type=summary',f'?view=month&month=2026-10&report_type=employee&personale_id={worker.id}',f'?view=month&month=2026-10&report_type=site&site_id={o["site"].id}']:
        html=o['client'].get('/manager/personale/presenze'+query)
        assert html.status_code==200 and 'Personale Mario' not in html.text
    o['actor'][0]=o['admin']
    html=o['client'].get('/manager/personale/presenze?week_start=2026-10-12&show_excluded=true')
    assert html.status_code==200 and 'Personale Mario' in html.text and '7.0h' in html.text
    assert post(o,url,{'people':[dict(person_id=worker.id,included=True,expected=False)]}).status_code==200
    assert db.query(PersonalePresenza).count()==1


def test_attendance_batch_is_atomic_and_admins_have_no_automatic_exemption(setup):
    o=setup;db=o['db'];admin_person=Personale(nome='Admin',cognome='Incluso',user_id=o['admin'].id,attivo=True)
    db.add(admin_person);db.commit();assert admin_person.incluso_presenze
    body={'people':[dict(person_id=o['worker'].id,included=False,expected=True),dict(person_id=admin_person.id,included=False,expected=False)]}
    assert post(o,'/manager/personale/presenze/elenco',body).status_code==409
    db.expire_all();assert o['worker'].incluso_presenze and admin_person.incluso_presenze
    body={'people':[dict(person_id=admin_person.id,included=False,expected=True)]}
    assert post(o,'/manager/personale/presenze/elenco',body).status_code==200
    assert o['worker'].incluso_presenze and not admin_person.incluso_presenze


def test_existing_database_adds_flag_with_true_default_idempotently(setup):
    o=setup;db=o['db'];engine=db.get_bind();person_id=o['worker'].id;db.commit()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE personale DROP COLUMN incluso_presenze'))
    for _ in range(2):ensure_model_columns(engine,(Base.metadata,SQLModel.metadata))
    db.expire_all();assert db.get(Personale,person_id).incluso_presenze is True
    assert 'incluso_presenze' in {c['name'] for c in inspect(engine).get_columns('personale')}
