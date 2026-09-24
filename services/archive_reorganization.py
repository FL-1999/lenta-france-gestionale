"""Resumable relocation of verified legacy copies; exclusions/trash never touched."""
from datetime import datetime, timedelta
import json
import uuid

from sqlalchemy import or_, update

from models import CloudAsset, CloudRun
from services.archive_layout import legacy_filter, readable_location
from services.sharepoint_client import CloudError, GraphClient, SharePointConfig


def reorganize_batch(factory, config=None, client=None, limit=3):
    config = config or SharePointConfig.from_env()
    result = {"moved": 0, "failed": 0, "paused": not config.enabled}
    if not config.enabled:
        return result
    graph = client
    try:
        for _ in range(limit):
            now = datetime.utcnow()
            token = uuid.uuid4().hex
            eligible = (CloudAsset.status == "verified") & legacy_filter() & or_(
                CloudAsset.next_attempt.is_(None), CloudAsset.next_attempt <= now) & or_(
                CloudAsset.lease_token.is_(None), CloudAsset.lease_until < now)
            with factory() as db:
                candidate = db.query(CloudAsset.id).filter(eligible).order_by(CloudAsset.id).first()
                if not candidate:
                    break
                claimed = db.execute(update(CloudAsset).where(CloudAsset.id == candidate.id, eligible).values(
                    lease_token=token, lease_until=now + timedelta(minutes=30), attempts=CloudAsset.attempts + 1))
                db.commit()
                if claimed.rowcount != 1:
                    continue
                asset = db.get(CloudAsset, candidate.id)
                old_path = asset.remote_path
                try:
                    if not asset.item_id or not asset.drive_id:
                        raise CloudError("archive_destination_unknown")
                    if graph is None:
                        graph = GraphClient(config)
                    if graph.check_destination() != asset.drive_id:
                        raise CloudError("destination_mismatch")
                    parts, filename = readable_location(db, asset)
                    new_path = "/".join(parts + [filename])
                    graph.move_archive_copy(asset.drive_id, asset.item_id, parts, filename,
                                            asset.sha256, asset.size_bytes)
                    values = dict(remote_path=new_path, verified_at=datetime.utcnow(),
                                  error_code=None, next_attempt=None)
                    result["moved"] += 1
                    details = dict(asset_id=asset.id, old_path=old_path, new_path=new_path)
                except Exception as exc:
                    code = exc.code if isinstance(exc, CloudError) else "unexpected_error"
                    delay = max(getattr(exc, "retry_after", 60), min(60 * 2 ** min(asset.attempts, 10), 86400))
                    values = dict(error_code="reorder_" + code,
                                  next_attempt=datetime.utcnow() + timedelta(seconds=delay))
                    result["failed"] += 1
                    details = dict(asset_id=asset.id, error=code)
                saved = db.execute(update(CloudAsset).where(CloudAsset.id == asset.id,
                    CloudAsset.lease_token == token).values(**values, lease_token=None, lease_until=None))
                if saved.rowcount != 1:
                    db.rollback()
                    raise CloudError("selection_busy_or_changed")
                db.add(CloudRun(kind="reorganization", status="error" if values.get("error_code") else "complete",
                    finished_at=datetime.utcnow(), details=json.dumps(details)))
                db.commit()
    finally:
        if graph is not None and client is None:
            graph.close()
    return result
