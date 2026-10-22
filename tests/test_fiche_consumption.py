from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker
from models import Fiche, FicheTypeEnum, FicheConsumptionAlert, FicheReviewEvent, Notification, RoleEnum
from services.fiche_consumption import consumption, view, validation_token, site_summary, backfill, NOTIFICATION_TYPE
from test_operations import operations
from test_assistant_integration import assistant


def make_fiche(o, actual=15, panel=1, depth=10):
    f = Fiche(site_id=o['site'].id, created_by_id=o['manager'].id, date=date(2026, 10, 22),
              numero_pannello=panel, panel_name=f'P{panel}', fiche_type=FicheTypeEnum.produzione,
              description='Test consumi', tipologia_scavo='paratia', profondita_totale=depth,
              larghezza_pannello=2, altezza_pannello=1, quota_partenza=15, quota_tn=16,
              metri_cubi_gettati=actual)
    o['db'].add(f); o['db'].commit()
    return f


def pending(o):
    return o['db'].query(Notification).filter_by(notification_type=NOTIFICATION_TYPE, is_read=False)


@pytest.mark.parametrize('actual,expected', [(0,'shortage'),(19.999,'shortage'),(20,None),
                                           (24,None),(24.0001,'excess'),(None,None)])
def test_exact_thresholds_and_missing_measurements(actual, expected):
    f = SimpleNamespace(site_id=1, tipologia_scavo='paratia', profondita_totale=10,
                        larghezza_pannello=2, altezza_pannello=1, diametro_palo=None, metri_cubi_gettati=actual)
    assert consumption(f)['kind'] == expected
    f.larghezza_pannello = 0
    assert consumption(f)['kind'] is None
    f.tipologia_scavo='palo'; f.diametro_palo=1
    f.metri_cubi_gettati=consumption(f)['theoretical'] * 1.2
    assert consumption(f)['kind'] is None
    f.metri_cubi_gettati -= 5
    assert consumption(f)['kind'] == 'shortage'


def test_admin_and_manager_validate_without_editing_and_changes_reopen(assistant):
    o=assistant; db=o['db']; c=o['client']
    manager=o['outsider']; manager.role=RoleEnum.manager; db.commit()
    f=make_fiche(o)
    assert pending(o).count() == 2
    assert {n.recipient_user_id for n in pending(o)} == {o['manager'].id,manager.id}
    assert '5,00 m³ in meno' in pending(o).first().message
    assert pending(o).first().target_url == f'/manager/fiches/{f.id}#fiche-consumption'
    html=c.get(f'/manager/fiches/{f.id}').text
    assert 'kpi-card--consumption-alert' in html and 'Valida consumo' in html
    o['actor'][0]=manager
    before=(f.metri_cubi_gettati, f.review_status, f.review_revision)
    token=validation_token(f, manager)
    url=f'/manager/fiches/{f.id}/valida-consumo'
    for _ in range(2):
        response=c.post(url,data={'csrf':token},follow_redirects=False)
        assert response.status_code == 303, response.text
    db.expire_all()
    assert before == (f.metri_cubi_gettati, f.review_status, f.review_revision)
    assert not pending(o).count()
    assert db.query(FicheReviewEvent).filter_by(action='consumption_validated').count()==1
    assert db.get(FicheConsumptionAlert,f.id).validated_by_id==manager.id
    assert view(db,f)['validated'] and not view(db,f)['active']
    html=c.get(f'/manager/fiches/{f.id}').text
    assert 'kpi-card--consumption-alert' not in html and 'Consumo validato' in html
    f.notes='Nota senza modifica dei consumi'; db.commit()
    assert view(db,f)['validated']
    f.metri_cubi_gettati=16; db.commit()
    assert view(db,f)['active'] and pending(o).count()==2
    assert c.post(url,data={'csrf':token}).status_code==409
    f.metri_cubi_gettati=22; db.commit()
    assert not view(db,f)['active'] and not pending(o).count()
    f.metri_cubi_gettati=15; db.commit()
    assert view(db,f)['active']  # Returning to an earlier value does not reuse its old validation.


def test_alerts_cannot_be_dismissed_from_bell_and_survive_retention(assistant):
    o=assistant; db=o['db']; c=o['client']; f=make_fiche(o, actual=25)
    n=pending(o).one(); nid=n.id
    n.created_at=datetime.utcnow()-timedelta(days=45)
    db.add_all(Notification(notification_type='test', message=str(i), recipient_user_id=o['manager'].id,
                            is_read=False, created_at=datetime.utcnow()) for i in range(105)); db.commit()
    result=c.get('/api/notifications/recent').json()
    assert result['notifications'][0]['id']==nid
    assert result['notifications'][0]['requires_action'] is True
    for path,payload in [('/api/notifications/mark-read',{'notification_id':nid}),
                         ('/api/notifications/mark-read',{'mark_all':True}),
                         (f'/api/notifications/{nid}/read',{}),('/api/notifications/clear-all',{})]:
        response=c.post(path,json=payload); assert response.status_code==200
        db.expire_all(); assert pending(o).count()==1
    assert c.get('/api/notifications/unread-count').json()['unread_count']==1
    o['actor'][0]=o['capo']
    assert not c.get('/api/notifications/recent').json()['notifications']


def test_permissions_csrf_stale_values_and_shared_resolution(assistant):
    o=assistant; c=o['client']; db=o['db']; f=make_fiche(o)
    url=f'/manager/fiches/{f.id}/valida-consumo'; token=validation_token(f,o['manager'])
    assert c.post(url,data={'csrf':'bad'}).status_code==409
    assert c.post(url,data={'csrf':token},headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert c.post(url,data={'csrf':token},headers=o['headers']).status_code==403
    o['actor'][0]=o['capo']
    assert c.post(url,data={'csrf':validation_token(f,o['capo'])}).status_code==403
    o['actor'][0]=o['manager']
    f.larghezza_pannello=3; db.commit()
    assert c.post(url,data={'csrf':token}).status_code==409
    assert view(db,f)['active']


def test_summary_uses_weighted_totals_without_hiding_opposite_alerts(assistant):
    o=assistant; a=make_fiche(o,actual=10); b=make_fiche(o,actual=30,panel=2)
    missing=make_fiche(o,actual=None,panel=3)
    result=site_summary(o['db'],[a,b,missing])
    assert result['actual']==result['theoretical']==40 and result['percentage']==0
    assert len(result['pending'])==2 and result['missing']==1 and result['included']==2
    page=o['client'].get(f'/manager/cantieri/{o["site"].id}')
    assert page.status_code==200 and 'Allarmi da validare' in page.text
    assert f'/manager/fiches/{a.id}#fiche-consumption' in page.text


def test_backfill_is_idempotent_preserves_decisions_and_delete_resolves(assistant):
    o=assistant; db=o['db']; f=make_fiche(o)
    factory=sessionmaker(bind=db.get_bind())
    before=(f.review_status,f.review_revision)
    backfill(factory); backfill(factory); db.expire_all()
    assert pending(o).count()==1 and before==(f.review_status,f.review_revision)
    o['client'].post(f'/manager/fiches/{f.id}/valida-consumo',data={'csrf':validation_token(f,o['manager'])})
    backfill(factory); db.expire_all()
    assert view(db,f)['validated'] and not pending(o).count()
    f.metri_cubi_gettati=18; db.commit(); assert pending(o).count()==1
    db.delete(f); db.commit()
    assert not pending(o).count() and not db.query(FicheConsumptionAlert).count()


def test_rollback_leaves_no_alert_and_no_notification(assistant):
    o=assistant; db=o['db']; f=make_fiche(o,actual=22)
    f.metri_cubi_gettati=10; db.flush(); db.rollback()
    assert not db.query(FicheConsumptionAlert).count() and not pending(o).count()


def test_existing_fiches_are_checked_without_reopening_official_review(assistant):
    o=assistant; db=o['db']
    inserted=db.execute(Fiche.__table__.insert().values(site_id=o['site'].id,
        created_by_id=o['manager'].id,date=date(2026,10,22),numero_pannello=7,
        panel_name='P7',fiche_type=FicheTypeEnum.produzione,description='Fiche già esistente',
        tipologia_scavo='paratia',profondita_totale=10,larghezza_pannello=2,
        altezza_pannello=1,metri_cubi_gettati=30))
    fid=inserted.inserted_primary_key[0]; db.commit()
    assert not db.query(FicheConsumptionAlert).count()
    backfill(sessionmaker(bind=db.get_bind())); db.expire_all()
    f=db.get(Fiche,fid)
    assert f.review_status=='confirmed' and f.review_revision==1
    assert view(db,f)['active'] and pending(o).count()==1
