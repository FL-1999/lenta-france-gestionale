import re
import pytest
from sqlalchemy import create_engine, text
from models import Fiche, Notification, RoleEnum, Base, FicheReviewEvent
from services.fiche_review import review_token
from test_operations import operations
from test_assistant_integration import assistant, propose, API
from test_site_pours import setup
from utils.production_stats import compute_site_production


def pending_fiche(o):
    setup(o)
    payload = dict(cantiere_id=o['site'].id, numero_pannello=1, data_scavo='2026-10-05',
        operatore='Squadra', tipologia_scavo='paratia', profondita_totale=10,
        strato_da=[0], strato_a=[10], strato_materiale=['sabbia'])
    proposal = propose(o, payload, 'fiche.create')
    assert proposal.status_code == 201, proposal.text
    assert o['db'].query(Fiche).count() == 0
    path = API + '/proposals/' + proposal.json()['id'] + '/submit-fiche'
    response = o['client'].post(path, headers=o['headers'])
    assert response.status_code == 200, response.text
    again = o['client'].post(path, headers=o['headers'])
    assert again.json()['result'] == response.json()['result']
    fiche = o['db'].query(Fiche).one()
    return fiche


def test_chat_submission_queue_notification_and_owner_confirmation(assistant):
    o = assistant; c = o['client']; db = o['db']
    f = pending_fiche(o)
    assert f.review_status == 'pending'
    db.refresh(o['site'])
    assert o['site'].paratie_done_panels == 0
    notification = db.query(Notification).filter_by(notification_type='fiche_review', is_read=False).one()
    assert notification.recipient_user_id == o['manager'].id
    assert str(f.panel_label) in notification.message
    assert notification.target_url == f'/manager/fiches/{f.id}'
    detail = c.get(notification.target_url)
    assert detail.status_code == 200 and 'Conferma fiche' in detail.text
    assert c.get('/manager/fiches?review_status=pending').status_code == 200
    csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', detail.text)[1]
    url = notification.target_url + '/conferma'
    assert c.post(url, data={'csrf':csrf}, headers=o['headers']).status_code == 403
    assert c.post(url, data={'csrf':csrf}, headers={'sec-fetch-site':'cross-site'}).status_code == 403
    o['actor'][0] = o['capo']
    assert c.post(url, data={'csrf':csrf}).status_code == 403
    o['actor'][0] = o['manager']
    assert c.post(url, data={'csrf':csrf}, follow_redirects=False).status_code == 303
    db.expire_all()
    assert f.review_status == 'confirmed' and f.reviewed_by_id == o['manager'].id
    assert o['site'].paratie_done_panels == 1
    assert not db.query(Notification).filter_by(notification_type='fiche_review', is_read=False).count()
    assert db.query(FicheReviewEvent).filter_by(action='confirmed').count() == 1
    c.post(url, data={'csrf':csrf})
    assert db.query(FicheReviewEvent).filter_by(action='confirmed').count() == 1


def test_changes_reopen_review_and_reject_stale_confirmation(assistant):
    o = assistant; db = o['db']; f = pending_fiche(o)
    url = f'/manager/fiches/{f.id}/conferma'
    old_token = review_token(f, o['manager'])
    f.hours = 7
    db.commit()
    assert o['client'].post(url, data={'csrf':old_token}).status_code == 409
    assert o['client'].post(url, data={'csrf':review_token(f,o['manager'])}, follow_redirects=False).status_code == 303
    f.metri_cubi_gettati = 20
    db.commit(); db.expire_all()
    assert f.review_status == 'pending' and f.reviewed_at is None
    assert o['site'].paratie_done_panels == 0
    assert db.query(FicheReviewEvent).filter_by(action='edited').count() >= 2
    assert db.query(Notification).filter_by(notification_type='fiche_review', is_read=False).count() == 1


def test_other_administrator_cannot_confirm_owner_fiche(assistant):
    o = assistant; f = pending_fiche(o)
    o['outsider'].role = RoleEnum.admin; o['db'].commit()
    o['actor'][0] = o['outsider']
    assert o['client'].post(f'/manager/fiches/{f.id}/conferma',
        data={'csrf':review_token(f,o['outsider'])}).status_code == 403


def test_chat_submit_cannot_execute_report_or_expired_fiche(assistant):
    o=assistant
    p=propose(o).json()
    assert o['client'].post(API+'/proposals/'+p['id']+'/submit-fiche',headers=o['headers']).status_code == 403
    f = pending_fiche(o)
    from models import AssistantProposal
    from datetime import datetime, timedelta
    row = o['db'].query(AssistantProposal).filter_by(kind='fiche.create').one()
    row.state='pending'; row.expires_at=datetime.utcnow()-timedelta(minutes=1)
    o['db'].commit()
    assert o['client'].post(API+'/proposals/'+row.id+'/submit-fiche',headers=o['headers']).status_code == 410
    assert o['db'].query(Fiche).count() == 1


def test_site_submission_is_pending_and_layer_edit_reopens_review(assistant):
    o=assistant; db=o['db']; setup(o, labels=('P1','P2'))
    o['actor'][0]=o['capo']
    response=o['client'].post('/capo/fiches/nuova', data={
        'cantiere_id':o['site'].id,'numero_pannello':1,'data_scavo':'2026-10-07',
        'operatore':'Squadra cantiere','tipologia_scavo':'paratia','profondita_totale':10,
        'strato_da':[0],'strato_a':[10],'strato_materiale':['sabbia']},follow_redirects=False)
    assert response.status_code == 303, response.text
    f=db.query(Fiche).one(); assert f.review_status == 'pending'
    o['actor'][0]=o['manager']
    assert o['client'].post(f'/manager/fiches/{f.id}/conferma',data={
        'csrf':review_token(f,o['manager'])},follow_redirects=False).status_code==303
    f.stratigrafie[0].materiale='argilla';db.commit();db.refresh(f)
    assert f.review_status == 'pending'
    db.refresh(o['site']);assert o['site'].paratie_done_panels == 0


def test_additive_migration_keeps_old_fiches_confirmed():
    from database import ensure_model_columns
    engine = create_engine('sqlite://')
    with engine.begin() as con:
        con.execute(text('CREATE TABLE fiches (id INTEGER PRIMARY KEY)'))
        con.execute(text('INSERT INTO fiches (id) VALUES (1)'))
    ensure_model_columns(engine, (Base.metadata,))
    with engine.connect() as con:
        assert con.execute(text('SELECT review_status, review_revision FROM fiches')).one() == ('confirmed',1)
    engine.dispose()
