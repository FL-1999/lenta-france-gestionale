"""Delete site-owned records atomically; detach shared company records."""
from sqlalchemy import or_, select, update, delete
from models import (Site, Report, ReportWorker, ReportDraft, ReportReview, ReportReviewEvent,
    ResourcePlan, SiteDocument, DocumentVersion, GabbiaCella, Machine, MachineSiteAssignment,
    MachineNote, PersonalePresenza, PurchaseOrder, PurchaseDelivery, MagazzinoRichiesta,
    MagazzinoMovimento, TrasportoViaggio, TrasportoTappa, MovimentoAttrezzatura)


def delete_site_records(db, site):
    """Caller owns the transaction and audit; never commit or suppress errors here."""
    sid=site.id
    # Capture older originals too, before the bulk delete bypasses mapper events.
    from services.cloud_archive import _document_saved, _plan_saved
    from models import SitePlan
    for document in db.query(SiteDocument).filter_by(site_id=sid):
        _document_saved(None, db.connection(), document)
    for plan in db.query(SitePlan).filter_by(site_id=sid):
        _plan_saved(None, db.connection(), plan)
    report_ids=select(Report.id).where(Report.site_id==sid)
    document_ids=select(SiteDocument.id).where(SiteDocument.site_id==sid)
    db.execute(update(ReportDraft).where(ReportDraft.submitted_report_id.in_(report_ids)).values(submitted_report_id=None))
    db.execute(delete(ReportReviewEvent).where(ReportReviewEvent.report_id.in_(report_ids)))
    db.execute(delete(ReportReview).where(ReportReview.report_id.in_(report_ids)))
    db.execute(delete(DocumentVersion).where(or_(DocumentVersion.document_id.in_(document_ids),DocumentVersion.root_id.in_(document_ids))))
    db.execute(delete(SiteDocument).where(SiteDocument.site_id==sid))
    db.execute(delete(GabbiaCella).where(GabbiaCella.site_id==sid))
    db.execute(delete(ResourcePlan).where(ResourcePlan.site_id==sid))
    # Attendance is company history: preserve hours, remove dangling links.
    attendance=PersonalePresenza.__table__
    db.execute(update(attendance).where(attendance.c.report_id.in_(report_ids)).values(report_id=None))
    db.execute(update(attendance).where(attendance.c.site_id==sid).values(site_id=None))
    # Use model columns, not guessed SQL names (stops have just site_id).
    references=(
        (PurchaseOrder,('site_id','delivery_site_id')),
        (PurchaseDelivery,('delivery_site_id',)),
        (MagazzinoRichiesta,('cantiere_id',)),(MagazzinoMovimento,('cantiere_id',)),
        (TrasportoViaggio,('origine_site_id','destinazione_site_id')),
        (TrasportoTappa,('site_id',)),
        (MovimentoAttrezzatura,('origine_site_id','destinazione_site_id')),
        (Machine,('site_id',)),(MachineSiteAssignment,('site_id',)),
        (MachineNote,('site_id',)),(ReportWorker,('site_id',)),
    )
    for model,columns in references:
        table=model.__table__
        for name in columns:
            db.execute(update(table).where(table.c[name]==sid).values({name:None}))
    # Prevent the old Site.machines delete-orphan cascade from deleting assets.
    db.expire(site,['machines'])
    db.delete(site)
    db.flush()
