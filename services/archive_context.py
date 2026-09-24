"""Read-only provenance for archive copies, without loading PDF/preview blobs."""
from datetime import datetime

from sqlalchemy import and_, case, or_

from models import Site, SiteDocument, SitePlan, CloudPlanPublication
from services.plan_selection import current_plan


def archive_context(db, assets):
    site_ids = {a.site_id for a in assets if a.site_id is not None}
    plan_ids = {int(a.source_id) for a in assets
                if a.kind in ("plan", "plan_preview") and a.source_id.isdigit()}
    document_ids = {int(a.source_id) for a in assets
                    if a.kind == "document" and a.source_id.isdigit()}
    sites = {row.id: row.name for row in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))}
    # Project only the metadata. Approval JSON and file blobs can be large.
    plans = db.query(SitePlan.id, SitePlan.site_id, SitePlan.filename, SitePlan.created_at,
                     SitePlan.removed_at, SitePlan.approved_at,
                     case((and_(SitePlan.approved.isnot(None), SitePlan.approved != ""), True),
                          else_=False).label("approved")).filter(
        or_(SitePlan.site_id.in_(site_ids), SitePlan.id.in_(plan_ids))).all()
    plans_by_id = {row.id: row for row in plans}
    publications = {row.plan_id: row for row in db.query(CloudPlanPublication).filter(CloudPlanPublication.plan_id.in_(plan_ids))}
    current, latest = {}, {}
    for site_id in sites:
        rows = [row for row in plans if row.site_id == site_id]
        chosen = current_plan(rows)
        current[site_id] = chosen.id if chosen else None
        uploaded = max(rows, key=lambda row: (row.created_at or datetime.min, row.id), default=None)
        latest[site_id] = uploaded.id if uploaded else None
    documents = {row.id: row for row in db.query(SiteDocument.id, SiteDocument.site_id,
                                               SiteDocument.created_at).filter(SiteDocument.id.in_(document_ids))}
    result = {}
    for asset in assets:
        info = dict(site_name=sites.get(asset.site_id), uploaded_at=None, archived_at=asset.created_at,
                    plan_id=None, plan_filename=None, state=None, latest=False, confirmed=False, plan_url=None, publication_number=None)
        if asset.kind in ("plan", "plan_preview"):
            plan = plans_by_id.get(int(asset.source_id)) if asset.source_id.isdigit() else None
            info["plan_id"] = asset.source_id
            publication = publications.get(int(asset.source_id)) if asset.source_id.isdigit() else None
            if publication and publication.site_id == asset.site_id:
                info["publication_number"] = publication.number
            if plan and plan.site_id == asset.site_id:
                info.update(uploaded_at=plan.created_at, plan_filename=plan.filename,
                            confirmed=bool(plan.approved), latest=latest.get(asset.site_id) == plan.id)
                if plan.removed_at is not None:
                    info["state"] = "removed"
                elif not info["site_name"]:
                    info["state"] = "unavailable"
                else:
                    info["state"] = ("current" if current.get(asset.site_id) == plan.id
                                     else "draft" if not plan.approved else "previous")
                    info["plan_url"] = f"/manager/cantieri/{asset.site_id}/pianta?plan_id={plan.id}"
            else:
                info["state"] = "unavailable"
        elif asset.kind == "document" and asset.source_id.isdigit():
            doc = documents.get(int(asset.source_id))
            if doc and doc.site_id == asset.site_id:
                info["uploaded_at"] = doc.created_at
        result[asset.id] = info
    return result
