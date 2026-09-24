"""Only approved original PDFs are published; drafts/previews stay local."""
from datetime import datetime

from sqlalchemy import String, cast, exists, func, or_, select, update

from models import CloudAsset, CloudPlanPublication, Site, SitePlan


def publication_exists():
    return exists(select(CloudPlanPublication.plan_id).where(
        cast(CloudPlanPublication.plan_id, String) == CloudAsset.source_id,
        CloudPlanPublication.site_id == CloudAsset.site_id))


def transfer_allowed():
    return (CloudAsset.kind != "plan_preview") & ((CloudAsset.kind != "plan") | publication_exists())


def register_approved_plans(db, site_id=None):
    query = db.query(SitePlan.site_id).filter(SitePlan.approved.isnot(None), SitePlan.approved != "",
        SitePlan.removed_at.is_(None), ~exists(select(CloudPlanPublication.plan_id).where(
            CloudPlanPublication.plan_id == SitePlan.id)))
    if site_id is not None:
        query = query.filter(SitePlan.site_id == site_id)
    for (sid,) in query.distinct().order_by(SitePlan.site_id).all():
        # Serialize number allocation for concurrent approvals on PostgreSQL.
        if not db.query(Site.id).filter_by(id=sid).with_for_update().first():
            continue
        rows = db.query(SitePlan.id, SitePlan.approved_at, SitePlan.created_at).filter(
            SitePlan.site_id == sid, SitePlan.approved.isnot(None), SitePlan.approved != "",
            SitePlan.removed_at.is_(None)).order_by(
                func.coalesce(SitePlan.approved_at, SitePlan.created_at), SitePlan.id).all()
        number = db.query(func.max(CloudPlanPublication.number)).filter_by(site_id=sid).scalar() or 0
        for row in rows:
            if db.get(CloudPlanPublication, row.id):
                continue
            number += 1
            db.add(CloudPlanPublication(plan_id=row.id, site_id=sid, number=number,
                confirmed_at=row.approved_at or row.created_at or datetime.utcnow()))
            db.flush()


def reconcile_plan_archives(db, site_id=None):
    register_approved_plans(db, site_id)
    available = or_(CloudAsset.lease_token.is_(None), CloudAsset.lease_until < datetime.utcnow())
    scope = (CloudAsset.site_id == site_id) if site_id is not None else True
    # Do not change owner exclusions, trash, or tombstones. Recorded remote
    # IDs/paths remain intact: this policy does not delete existing cloud files.
    db.execute(update(CloudAsset).where(scope, available,
        CloudAsset.status.in_(("pending", "error", "sending", "verified")), ~transfer_allowed()).values(
            status="local", error_code=None, next_attempt=None, lease_token=None, lease_until=None),
        execution_options={"synchronize_session": False})
    db.execute(update(CloudAsset).where(scope, available, CloudAsset.status == "local",
        CloudAsset.kind == "plan", publication_exists()).values(status="pending", next_attempt=None,
        error_code=None, lease_token=None, lease_until=None), execution_options={"synchronize_session": False})
