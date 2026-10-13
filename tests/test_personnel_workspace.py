from datetime import date
from uuid import uuid4
import json
import pytest
from fastapi import HTTPException
from models import (User, RoleEnum, Personale, PersonalePresenza, PersonnelRequest, PersonnelAttachment,
    PersonnelAssignment, PersonnelTeam, PersonnelAttendanceLink, PersonnelEvent, Notification, Depot)
from test_operations import operations, report_payload
from routes.personnel import token
from services import personnel as svc
from personale_presenze_repository import upsert_personale_presenza


@pytest.fixture
def personnel(operations):
    o=operations; db=o['db']
    staff=User(email='staff@example.test',full_name='Luca Test',role=RoleEnum.personale,hashed_password='x',is_active=True)
    db.add(staff);db.flush()
    worker=Personale(nome='Luca',cognome='Test',user_id=staff.id,attivo=True)
    db.add(worker);db.commit()
    o.update(staff=staff,worker=worker)
    return o


def post(o,url,body,actor=None):
    if actor:o['actor'][0]=actor
    return o['client'].post(url,json=body,headers={'X-CSRF-Token':token(o['actor'][0])})


def submit(o,kind='leave',start='2026-11-02',end='2026-11-03',**extra):
    data={'kind':kind,'start_date':start,'end_date':end,'submission_key':uuid4().hex,**extra}
    return o['client'].post('/mio-spazio/richieste',data={'payload':json.dumps(data)},headers={'X-CSRF-Token':token(o['actor'][0])})


def decide(o,r,**extra):
    return post(o,f"/manager/personale/richieste/{r['id']}/esito",dict(version=r['version'],status='approved',classification='FERIE',end_date=r['end_date'],**extra),o['manager'])


def test_personal_role_redirect_and_all_pages(personnel):
    from auth import get_redirect_for_role
    o=personnel;o['actor'][0]=o['staff'];c=o['client']
    assert get_redirect_for_role(RoleEnum.personale)=='/mio-spazio'
    assert c.get('/mio-spazio').status_code==200
    assert c.get('/mio-spazio/data').json()['person']['id']==o['worker'].id
    assert c.get('/manager/personale/workspace-data').status_code==403
    assert c.get('/manager/personale/richieste').status_code==403
    assert c.get('/capo/squadra',params={'site_id':o['site'].id,'day':'2026-11-02'}).status_code==403
    o['actor'][0]=o['manager']
    for page in ['/manager/personale/richieste','/manager/personale/squadre']:
        assert c.get(page).status_code==200


def test_csrf_and_cross_site_fail_closed(personnel):
    o=personnel;o['actor'][0]=o['staff'];body={'payload':json.dumps(dict(kind='leave',start_date='2026-11-02',end_date='2026-11-03',submission_key=uuid4().hex))}
    assert o['client'].post('/mio-spazio/richieste',data=body).status_code==403
    assert o['client'].post('/mio-spazio/richieste',data=body,headers={'X-CSRF-Token':token(o['staff']),'Origin':'https://other.test'}).status_code==403
    assert o['db'].query(PersonnelRequest).count()==0


def test_leave_approval_creates_shared_presences_and_private_reply(personnel):
    o=personnel;o['actor'][0]=o['staff'];db=o['db']
    response=submit(o,start='2026-11-06',end='2026-11-09');assert response.status_code==200,response.text
    row=response.json();assert db.query(PersonalePresenza).count()==0
    result=decide(o,row,response='Confermato',office_note='INTERNAL');assert result.status_code==200,result.text
    assert [p.attendance_date for p in db.query(PersonalePresenza).order_by(PersonalePresenza.attendance_date)]==[date(2026,11,6),date(2026,11,9)]
    o['actor'][0]=o['staff'];data=o['client'].get('/mio-spazio/data?month=2026-11-01').json()
    assert len(data['attendance'])==2 and data['requests'][0]['response']=='Confermato'
    assert 'INTERNAL' not in json.dumps(data)
    assert db.query(Notification).filter_by(recipient_user_id=o['staff'].id,notification_type='personnel_response').count()==1


def test_existing_hours_block_whole_decision_and_do_not_send_notification(personnel):
    o=personnel;o['actor'][0]=o['staff'];db=o['db'];row=submit(o).json()
    db.add(PersonalePresenza(personale_id=o['worker'].id,attendance_date=date(2026,11,3),status='WORK',hours=8));db.commit()
    response=decide(o,row);assert response.status_code==409,response.text
    db.expire_all();assert db.get(PersonnelRequest,row['id']).status=='pending'
    assert db.query(PersonalePresenza).count()==1
    assert db.query(Notification).filter_by(notification_type='personnel_response').count()==0


def test_stale_decision_and_cancellation_restore_only_owned_days(personnel):
    o=personnel;o['actor'][0]=o['staff'];row=submit(o).json();saved=decide(o,row).json()
    assert decide(o,row).status_code==409
    response=post(o,f"/manager/personale/richieste/{row['id']}/esito",{'version':saved['version'],'status':'cancelled','response':'Rientro anticipato','end_date':row['end_date']})
    assert response.status_code==200,response.text
    assert o['db'].query(PersonalePresenza).count()==0
    assert o['db'].query(PersonnelAttendanceLink).count()==0


def test_report_and_manual_edits_cannot_overwrite_absence(personnel):
    o=personnel;o['actor'][0]=o['capo'];db=o['db']
    row=submit(o,kind='absence',start='2026-09-16',end=None,reason='sickness').json()
    response=o['client'].post('/reports',json=report_payload(o));assert response.status_code==409,response.text
    db.rollback()
    with pytest.raises(HTTPException):upsert_personale_presenza(db,o['person'].id,date(2026,9,16),'WORK',hours=8)
    db.rollback();o['actor'][0]=o['manager']
    response=post(o,f"/manager/personale/richieste/{row['id']}/esito",{'version':1,'status':'acknowledged','classification':'MALATTIA','end_date':None})
    assert response.status_code==200,response.text
    assert db.query(PersonalePresenza).count()==0
    response=post(o,f"/manager/personale/richieste/{row['id']}/esito",{'version':2,'status':'acknowledged','classification':'MALATTIA','end_date':'2026-09-16'})
    assert response.status_code==200,response.text
    assert db.query(PersonalePresenza).one().status=='MALATTIA'


def test_certificate_encrypted_private_and_download_only(personnel):
    o=personnel;o['actor'][0]=o['staff'];db=o['db'];content=b'%PDF-1.4\nmedical-private-test'
    payload=dict(kind='absence',start_date='2026-11-02',reason='sickness',submission_key=uuid4().hex)
    response=o['client'].post('/mio-spazio/richieste',data={'payload':json.dumps(payload)},files={'attachment':('doctor.pdf',content,'application/pdf')},headers={'X-CSRF-Token':token(o['staff'])})
    assert response.status_code==200,response.text
    row=response.json();blob=db.query(PersonnelAttachment).one();assert content not in blob.encrypted_data
    url=f"/mio-spazio/richieste/{row['id']}/allegato"
    downloaded=o['client'].get(url);assert downloaded.content==content
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    assert 'no-store' in downloaded.headers['cache-control']
    o['actor'][0]=o['capo'];assert o['client'].get(url).status_code==403
    o['actor'][0]=o['manager'];assert o['client'].get(url).content==content


def test_upload_validation_rolls_back_request(personnel):
    o=personnel;o['actor'][0]=o['staff']
    payload=dict(kind='absence',start_date='2026-11-02',reason='sickness',submission_key=uuid4().hex)
    response=o['client'].post('/mio-spazio/richieste',data={'payload':json.dumps(payload)},files={'attachment':('evil.pdf',b'<script>alert(1)</script>','application/pdf')},headers={'X-CSRF-Token':token(o['staff'])})
    assert response.status_code==422
    assert o['db'].query(PersonnelRequest).count()==0


def test_cannot_submit_for_other_person_and_retry_is_idempotent(personnel):
    o=personnel;o['actor'][0]=o['staff']
    assert submit(o,person_id=o['person'].id).status_code==403
    key=uuid4().hex
    first=submit(o,submission_key=key);second=submit(o,submission_key=key)
    assert first.json()['id']==second.json()['id']
    assert o['db'].query(PersonnelRequest).count()==1


def test_teams_depots_effective_dates_overlap_and_absence_privacy(personnel):
    o=personnel;db=o['db'];o['actor'][0]=o['manager']
    team=post(o,'/manager/personale/squadre',{'name':'Nord','lead_id':o['capo'].id,'site_id':o['site'].id})
    assert team.status_code==200,team.text
    url=f"/manager/personale/squadre/{team.json()['id']}/assegnazioni"
    assigned=post(o,url,{'person_id':o['worker'].id,'start_date':'2026-11-01','end_date':'2026-11-30'})
    assert assigned.status_code==200,assigned.text
    assert post(o,url,{'person_id':o['worker'].id,'start_date':'2026-11-05','end_date':'2026-11-06'}).status_code==409
    db.rollback();o['actor'][0]=o['staff'];submit(o,kind='absence',reason='sickness',note='MEDICAL-PRIVATE')
    o['actor'][0]=o['capo'];result=o['client'].get('/capo/squadra',params={'site_id':o['site'].id,'day':'2026-11-02'})
    assert result.status_code==200 and result.json()['people'][0]['unavailable']
    assert 'MEDICAL-PRIVATE' not in result.text and 'sickness' not in result.text
    assert o['client'].get('/capo/squadra',params={'site_id':o['site'].id,'day':'2026-12-02'}).json()['people']==[]
    o['actor'][0]=o['staff'];assert o['client'].get('/mio-spazio/data').json()['assignments'][0]['team']=='Nord'
    o['actor'][0]=o['manager'];depot=Depot(name='Deposito');db.add(depot);db.commit()
    assert post(o,'/manager/personale/squadre',{'name':'Deposito','lead_id':o['capo'].id,'depot_id':depot.id}).status_code==200
    assert db.query(PersonalePresenza).count()==0


def test_account_link_admin_only_and_no_reassignment(personnel):
    o=personnel;db=o['db'];unlinked=Personale(nome='New',cognome='Person',attivo=True);db.add(unlinked);db.commit()
    url=f'/manager/personale/{unlinked.id}/account'
    assert post(o,url,{'user_id':o['staff'].id},o['manager']).status_code==403
    o['manager'].role=RoleEnum.admin;db.commit()
    assert post(o,url,{'user_id':o['staff'].id}).status_code==409
    assert db.get(Personale,unlinked.id).user_id is None


def test_manual_conflict_removal_is_explicit_audited_and_version_checked(personnel):
    o=personnel;o['actor'][0]=o['staff'];db=o['db'];row=submit(o).json()
    presence=PersonalePresenza(personale_id=o['worker'].id,attendance_date=date(2026,11,3),status='WORK',hours=8)
    db.add(presence);db.commit();o['actor'][0]=o['manager']
    request=o['client'].get('/manager/personale/workspace-data').json()['requests'][0];conflict=request['conflicts'][0]
    url=f"/manager/personale/richieste/{row['id']}/correggi-presenza"
    body={'attendance_id':presence.id,'snapshot':conflict['snapshot']}
    assert post(o,url,body,o['staff']).status_code==403
    assert post(o,url,{**body,'snapshot':'a'*64},o['manager']).status_code==409
    assert db.query(PersonalePresenza).count()==1
    assert post(o,url,body).status_code==200
    assert db.query(PersonnelEvent).filter_by(action='manual_attendance_removed').count()==1
    assert decide(o,row).status_code==200
    assert db.query(PersonalePresenza).count()==2


def test_daily_plan_overrides_team_without_rewriting_it(personnel):
    from models import ResourcePlan
    o=personnel;db=o['db'];o['actor'][0]=o['manager'];day=date(2026,11,2)
    team=post(o,'/manager/personale/squadre',{'name':'Nord','lead_id':o['capo'].id,'site_id':o['site'].id}).json()
    post(o,f"/manager/personale/squadre/{team['id']}/assegnazioni",{'person_id':o['worker'].id,'start_date':'2026-11-01','end_date':'2026-11-30'})
    db.add(ResourcePlan(day=day,site_id=o['other'].id,resource_type='person',resource_id=o['worker'].id,resource_label='Luca',created_by_id=o['manager'].id));db.commit()
    assert svc.effective_roster(db,o['site'].id,day)[1]==[]
    assert svc.effective_roster(db,o['other'].id,day)[1][0].id==o['worker'].id
    assert svc.effective_roster(db,o['site'].id,date(2026,11,3))[1][0].id==o['worker'].id


@pytest.mark.parametrize('start,end',[('2026-11-05','2026-11-01'),('2026-01-01','2028-01-01')])
def test_invalid_periods_fail(personnel,start,end):
    o=personnel;o['actor'][0]=o['staff'];assert submit(o,start=start,end=end).status_code==422
