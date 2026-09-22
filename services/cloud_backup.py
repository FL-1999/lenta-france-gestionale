"""Native database snapshots, separate restricted destination, no automatic deletion."""
from datetime import datetime
from contextlib import closing
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile

from models import CloudAsset, CloudRun
from services.cloud_archive import prepare_existing
from services.sharepoint_client import CloudError, GraphClient, SharePointConfig


def native_snapshot(engine, destination):
    if engine.dialect.name == "sqlite":
        output = destination / "database.sqlite3"
        raw = engine.raw_connection()
        try:
            with closing(sqlite3.connect(output)) as target:
                raw.driver_connection.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CloudError("backup_integrity_failed")
        finally:
            raw.close()
        return output
    if engine.dialect.name != "postgresql":
        raise CloudError("backup_database_unsupported")
    executable = shutil.which("pg_dump")
    if not executable:
        raise CloudError("pg_dump_missing")
    url = engine.url
    output = destination / "database.dump"
    # Credentials go in a short-lived private passfile, never arguments or logs.
    passfile = destination / ".pgpass"
    escape = lambda value: str(value or "").replace("\\", "\\\\").replace(":", "\\:")
    passfile.write_text(":".join(escape(v) for v in [url.host or "localhost", url.port or 5432,
        url.database, url.username, url.password]) + "\n", encoding="utf-8")
    passfile.chmod(0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env.update(PGHOST=url.host or "localhost", PGPORT=str(url.port or 5432), PGDATABASE=url.database or "",
               PGUSER=url.username or "", PGPASSFILE=str(passfile), PGCONNECT_TIMEOUT="15")
    for key, value in url.query.items():
        if key in {"sslmode", "sslrootcert", "sslcert", "sslkey", "options", "channel_binding"}:
            env["PG" + key.replace("_", "").upper()] = str(value)
    try:
        proc = subprocess.run([executable, "--format=custom", "--no-owner", "--no-acl", "--file", str(output)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800, check=False)
        if proc.returncode or not output.exists() or output.stat().st_size == 0:
            raise CloudError("pg_dump_failed")
    except subprocess.TimeoutExpired:
        raise CloudError("backup_timeout") from None
    finally:
        passfile.unlink(missing_ok=True)
    return output


def make_bundle(engine, destination):
    snapshot = native_snapshot(engine, destination)
    bundle = destination / "backup.zip"
    metadata = {"format": "lenta-native-backup-v1", "created_at": datetime.utcnow().isoformat(),
        "database": engine.dialect.name, "snapshot": snapshot.name,
        "includes": ["all database tables", "document blobs", "plan originals and geometry", "archived invoices and issued PDFs"],
        "excludes": ["server secrets/environment", "application source code (Git repository)"],
        "restore": "Restore into an isolated database first, using matching application code. See docs/sharepoint.md."}
    revision = os.getenv("RENDER_GIT_COMMIT", "")
    metadata["application_commit"] = revision if re.fullmatch(r"[a-fA-F0-9]{40}", revision) else None
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.write(snapshot, snapshot.name)
        archive.writestr("manifest.json", json.dumps(metadata, indent=2))
    return bundle


def send_backup(factory, config=None, client=None):
    config = config or SharePointConfig.from_env()
    if not config.enabled:
        raise CloudError("sync_disabled")
    graph = client or GraphClient(config)
    run_id = None
    try:
        drive = graph.check_destination(backup=True)
        with factory() as db:
            inventory = prepare_existing(db)
            if inventory["missing_count"]:
                raise CloudError("backup_missing_sources")
            run = CloudRun(kind="backup", status="running")
            db.add(run)
            db.commit()
            run_id = run.id
            engine = db.get_bind()
        with tempfile.TemporaryDirectory(prefix="lenta-backup-") as directory:
            bundle = make_bundle(engine, Path(directory))
            digest = hashlib.sha256()
            with bundle.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            name = f"lenta-{datetime.utcnow():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:12]}.zip"
            with bundle.open("rb") as stream:
                item_id = graph.upload(drive, ["Gestionale-Backups"], name, stream, bundle.stat().st_size, digest.hexdigest())
            details = {"filename": name, "drive_id": drive, "item_id": item_id,
                "sha256": digest.hexdigest(), "size_bytes": bundle.stat().st_size,
                "restore_tested": False}
        with factory() as db:
            row = db.get(CloudRun, run_id)
            row.status = "verified"
            row.details = json.dumps(details)
            row.finished_at = datetime.utcnow()
            db.commit()
        return details
    except Exception as exc:
        code = exc.code if isinstance(exc, CloudError) else "backup_failed"
        with factory() as db:
            row = db.get(CloudRun, run_id) if run_id else None
            if row is None:
                row = CloudRun(kind="backup", status="error")
                db.add(row)
            row.status, row.details, row.finished_at = "error", code, datetime.utcnow()
            db.commit()
        raise CloudError(code) from None
    finally:
        if client is None:
            graph.close()
