from datetime import date
import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import main
from models import (Site, RoleEnum, Machine, MachineSiteAssignment, MachineNote, SitePlan,
    Report, ReportReview, ReportReviewEvent, ReportDraft, ResourcePlan, SiteDocument,
    DocumentVersion, GabbiaCella, PersonalePresenza, PurchaseOrder, PurchaseDelivery,
    TrasportoViaggio, TrasportoTappa, AuditLog, SiteCoupe, SiteCoupeAssignment, Fiche, FicheTypeEnum)
from test_operations import operations


def prepare(o):
    db=o['db'];o['manager'].role=RoleEnum.admin;o['actor'][0]=o['manager'];db.commit()
    if db.bind.dialect.name=='sqlite': db.execute(text('PRAGMA foreign_keys=ON'))
    sid=o['site'].id;uid=o['manager'].id
    o['machine'].site_id=sid
    db.add(MachineSiteAssignment(machine_id=o['machine'].id,site_id=sid))
    db.add(MachineNote(machine_id=o['machine'].id,site_id=sid,operator_id=uid,text='Conservare nota'))
    order=PurchaseOrder(order_number='DELETE-TEST',site_id=sid,delivery_type='SITE',delivery_site_id=sid)
    trip=TrasportoViaggio(codice_viaggio='DELETE-TEST',data_partenza=date.today(),origine='Magazzino',destinazione='Cantiere',destinazione_site_id=sid)
    report=Report(site_id=sid,date=date.today(),site_name_or_code='Test',created_by_id=uid)
    doc=SiteDocument(site_id=sid,filename='test.pdf',data=b'fake-test-pdf')
    coupe=SiteCoupe(site_id=sid,nome='Coupe 1')
    db.add_all([order,trip,report,doc,coupe]);db.flush()
    db.add(PurchaseDelivery(order_id=order.id,delivery_number='B1',delivery_site_id=sid,delivery_type='SITE'))
    db.add(TrasportoTappa(viaggio_id=trip.id,site_id=sid,destinazione='Test'))
    db.add(ReportReview(report_id=report.id))
    db.add(ReportReviewEvent(report_id=report.id,status='submitted',user_id=uid))
    db.add(ReportDraft(user_id=uid,submitted_report_id=report.id))
    db.add(DocumentVersion(document_id=doc.id,root_id=doc.id,number=1))
    db.add(GabbiaCella(site_id=sid,numero=1))
    db.add(ResourcePlan(site_id=sid,day=date.today(),resource_type='person',resource_id=o['person'].id,resource_label='Test',created_by_id=uid))
    db.add(PersonalePresenza(site_id=sid,report_id=report.id,personale_id=o['person'].id,attendance_date=date.today(),status='presente',hours=8))
    db.add(SitePlan(site_id=sid,filename='test.pdf',pdf_data=b'fake',preview_data=b'fake',draft='{}'))
    db.add(SiteCoupeAssignment(site_id=sid,coupe_id=coupe.id,tipologia_scavo='paratia',numero_elemento=1))
    db.add(Fiche(site_id=sid,coupe_id=coupe.id,numero_pannello=1,created_by_id=uid,date=date.today(),fiche_type=FicheTypeEnum.produzione,description='Test',tipologia_scavo='paratia'))
    db.commit()
    return sid


def test_delete_populated_site_keeps_shared_assets_and_history(operations):
    o=operations;sid=prepare(o);name=o['site'].name;other_id=o['other'].id;machine_id=o['machine'].id
    r=o['client'].post(f'/manager/cantieri/{sid}/elimina',data={'conferma_nome':name},follow_redirects=False)
    assert r.status_code==303,r.text
    assert r.headers['location']=='/manager/cantieri?deleted=1'
    db=o['db'];db.expire_all()
    assert db.get(Site,sid) is None and db.get(Site,other_id) is not None
    for model in (SitePlan,SiteCoupe,SiteCoupeAssignment,Fiche,Report,ReportReview,ReportReviewEvent,SiteDocument,DocumentVersion,GabbiaCella,ResourcePlan):
        assert db.query(model).count()==0,model.__name__
    assert db.get(Machine,machine_id).site_id is None
    assert db.query(MachineSiteAssignment).one().site_id is None
    assert db.query(MachineNote).one().text=='Conservare nota'
    assert db.query(PurchaseOrder).one().site_id is None
    assert db.query(PurchaseDelivery).one().delivery_site_id is None
    assert db.query(TrasportoViaggio).one().destinazione_site_id is None
    assert db.query(TrasportoTappa).one().site_id is None
    attendance=db.query(PersonalePresenza).one()
    assert attendance.hours==8 and attendance.site_id is None and attendance.report_id is None
    assert db.query(ReportDraft).one().submitted_report_id is None
    assert db.query(AuditLog).filter_by(action='SITE_DELETED',target_id=sid).count()==1
    assert name not in o['client'].get('/manager/cantieri').text
    assert o['client'].post(f'/manager/cantieri/{sid}/elimina',data={'conferma_nome':name},follow_redirects=False).status_code==404


def test_delete_rolls_back_on_failure_and_never_reports_success(operations,monkeypatch):
    o=operations;sid=prepare(o)
    def failed_audit(*args,**kwargs): raise SQLAlchemyError('simulated database failure')
    monkeypatch.setattr(main,'log_audit_event',failed_audit)
    r=o['client'].post(f'/manager/cantieri/{sid}/elimina',data={'conferma_nome':o['site'].name},follow_redirects=False)
    assert r.status_code==409 and 'non è stato eliminato' in r.text
    db=o['db'];db.expire_all()
    assert db.get(Site,sid) is not None
    assert db.query(SitePlan).count()==db.query(Fiche).count()==db.query(DocumentVersion).count()==1
    assert db.query(PurchaseOrder).one().site_id==sid
    assert db.get(Machine,o['machine'].id).site_id==sid
    assert db.query(AuditLog).filter_by(action='SITE_DELETED').count()==0


def test_delete_requires_permission_and_exact_name(operations):
    o=operations;sid=o['site'].id;url=f'/manager/cantieri/{sid}/elimina'
    assert o['client'].post(url,data={'conferma_nome':o['site'].name}).status_code==403
    o['manager'].role=RoleEnum.admin;o['actor'][0]=o['manager'];o['db'].commit()
    assert o['client'].post(url,data={'conferma_nome':'wrong'}).status_code==400
    assert o['db'].get(Site,sid) is not None
