from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import zipfile

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from test_operations import operations
from models import CloudAsset, CloudRun, PurchaseOrder, SiteDocument, SitePlan, RoleEnum
from services.cloud_archive import enqueue, prepare_existing, sync_batch, legacy_invoice_path
from services.cloud_backup import make_bundle, send_backup
from services.sharepoint_client import CHUNK, CloudError, GraphClient, SharePointConfig


def config(**changes):
    return SharePointConfig(**{**dict(tenant="11111111-1111-1111-1111-111111111111",
        client_id="22222222-2222-2222-2222-222222222222", secret="NEVER-SHOW-THIS-SECRET",
        site_id="site", drive_id="docs", enabled=True, backup_site_id="private-site",
        backup_drive_id="private", backup_access_confirmed=True), **changes})


def factory(o):
    return sessionmaker(bind=o["db"].get_bind())


def admin(o):
    o["manager"].role = RoleEnum.admin
    o["actor"][0] = o["manager"]
    o["db"].commit()


def csrf(o):
    response = o["client"].get("/admin/sharepoint")
    assert response.status_code == 200, response.text
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


class ArchiveStub:
    def __init__(self, error=None):
        self.error = error
        self.uploads = []

    def check_destination(self, backup=False):
        return "private" if backup else "docs"

    def upload(self, drive, parts, filename, stream, size, sha):
        self.uploads.append((drive, parts, filename, stream.read(), size, sha))
        if self.error:
            raise CloudError(self.error, 300)
        assert hashlib.sha256(self.uploads[-1][3]).hexdigest() == sha
        assert len(self.uploads[-1][3]) == size
        return "remote-id"


def test_capture_is_transactional_and_survives_source_delete(operations):
    o = operations; db = o["db"]
    document = SiteDocument(site_id=o["site"].id, filename="test.pdf", data=b"PDF", size_bytes=3)
    db.add(document); db.flush()
    assert db.query(CloudAsset).count() == 1
    db.rollback()
    assert db.query(CloudAsset).count() == 0
    db.add(SiteDocument(site_id=o["site"].id, filename="kept.pdf", data=b"keep", size_bytes=4))
    db.commit()
    document = db.query(SiteDocument).one()
    db.delete(document); db.commit()
    assert db.query(CloudAsset).one().payload == b"keep"


def test_inventory_preserves_blobs_plans_and_legacy_invoices_idempotently(operations, tmp_path):
    o = operations; db = o["db"]
    plan = SitePlan(site_id=o["site"].id, filename="original.pdf", pdf_data=b"plan", preview_data=b"png", draft="{}")
    db.add(plan)
    order = PurchaseOrder(order_number="legacy", file_invoice="uploads/invoices/old.pdf")
    missing = PurchaseOrder(order_number="missing", file_invoice="uploads/invoices/gone.pdf")
    db.add_all([order, missing]); db.commit()
    (tmp_path / "old.pdf").write_bytes(b"invoice")
    first = prepare_existing(db, tmp_path)
    second = prepare_existing(db, tmp_path)
    assert first == second and first["missing_count"] == 1
    assert order.file_invoice.startswith("cloud:invoice:")
    assert db.query(CloudAsset).count() == 3
    assert (tmp_path / "old.pdf").read_bytes() == b"invoice"
    assert db.get(SitePlan, plan.id).pdf_data == b"plan"


@pytest.mark.parametrize("path", ["uploads/invoices/../secret", "uploads/invoices/sub/file", "uploads/invoices/C:/secret", "secret", "/etc/passwd"])
def test_legacy_invoice_paths_cannot_escape(path, tmp_path):
    with pytest.raises(CloudError):
        legacy_invoice_path(path, tmp_path)


def test_queue_retries_without_losing_source_or_duplicating_and_checks_hash(operations):
    o = operations; db = o["db"]
    for _ in range(2):
        enqueue(db, "document", 1, "a.pdf", b"original")
    db.commit()
    assert db.query(CloudAsset).count() == 1
    fail = ArchiveStub("permission_denied")
    assert sync_batch(factory(o), config(), fail)["failed"] == 1
    db.expire_all(); row = db.query(CloudAsset).one()
    assert row.status == "error" and row.payload == b"original" and row.next_attempt > datetime.utcnow()
    assert sync_batch(factory(o), config(), fail)["failed"] == 0
    row.next_attempt = None; db.commit()
    success = ArchiveStub()
    assert sync_batch(factory(o), config(), success)["verified"] == 1
    assert sync_batch(factory(o), config(), success)["verified"] == 0
    db.expire_all(); row = db.query(CloudAsset).one()
    assert row.status == "verified" and row.verified_at and row.payload == b"original"
    assert row.attempts == 2 and row.drive_id == "docs"
    enqueue(db, "document", 2, "bad.pdf", b"original"); db.commit()
    corrupt = db.query(CloudAsset).filter_by(source_id="2").one()
    corrupt.payload = b"corrupted"; db.commit()
    assert sync_batch(factory(o), config(), success)["failed"] == 1
    db.expire_all()
    assert db.get(CloudAsset, corrupt.id).error_code == "local_integrity_failed"
    assert len(success.uploads) == 1


def test_active_lease_is_skipped_and_expired_work_is_recovered(operations):
    o = operations; db = o["db"]
    enqueue(db, "document", 1, "a.pdf", b"original"); db.commit()
    row = db.query(CloudAsset).one()
    row.status = "sending"; row.lease_token = "other-worker"; row.lease_until = datetime.utcnow() + timedelta(minutes=20)
    db.commit()
    assert sync_batch(factory(o), config(), ArchiveStub())["verified"] == 0
    row.lease_until = datetime.utcnow() - timedelta(seconds=1); db.commit()
    assert sync_batch(factory(o), config(), ArchiveStub())["verified"] == 1


def test_disabled_sync_never_contacts_microsoft(operations):
    stub = ArchiveStub()
    assert sync_batch(factory(operations), config(enabled=False), stub)["paused"]
    assert not stub.uploads


def test_second_worker_cannot_upload_a_claimed_document(operations):
    o = operations
    enqueue(o["db"], "document", 1, "a.pdf", b"original"); o["db"].commit()
    second = ArchiveStub()
    class Competing(ArchiveStub):
        def upload(self, *args):
            assert sync_batch(factory(o), config(), second)["verified"] == 0
            return super().upload(*args)
    assert sync_batch(factory(o), config(), Competing())["verified"] == 1
    assert not second.uploads


def test_site_removal_does_not_cascade_to_document_archive(operations):
    from services.site_deletion import delete_site_records
    o = operations; db = o["db"]
    doc = SiteDocument(site_id=o["site"].id, filename="site.pdf", data=b"retained", size_bytes=8)
    db.add(doc); db.commit()
    delete_site_records(db, o["site"]); db.commit()
    assert db.query(CloudAsset).one().payload == b"retained"


def test_admin_page_csrf_french_and_secret_redaction(operations, monkeypatch):
    o = operations; c = o["client"]
    o["actor"][0] = o["manager"]
    assert c.get("/admin/sharepoint").status_code == 403
    admin(o)
    monkeypatch.setenv("SHAREPOINT_CLIENT_SECRET", "NEVER-SHOW-THIS-SECRET")
    page = c.get("/admin/sharepoint")
    assert "In attesa del tecnico" in page.text and "NEVER-SHOW-THIS-SECRET" not in page.text
    for path in ["prepara", "verifica", "riprova"]:
        assert c.post("/admin/sharepoint/" + path).status_code == 403
    token = csrf(o)
    assert c.post("/admin/sharepoint/prepara", data={"csrf": token}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/admin/sharepoint/prepara", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert c.post("/admin/sharepoint/verifica", data={"csrf": token}, follow_redirects=False).status_code == 303
    assert o["db"].query(CloudRun).filter_by(kind="connection").one().details == "configuration_missing"
    c.cookies.set("lang", "fr")
    assert "En attente du technicien" in c.get("/admin/sharepoint").text
    assert c.get("/admin/sharepoint/guida").status_code == 200


def test_archive_recovery_is_owner_only_even_for_other_admins(operations, monkeypatch):
    o = operations; db = o["db"]; admin(o)
    enqueue(db, "document", 1, "test.pdf", b"recover"); db.commit()
    row = db.query(CloudAsset).one()
    url = f"/admin/sharepoint/archivio/{row.id}"
    assert o["client"].get(url).status_code == 403
    monkeypatch.setenv("CLOUD_ARCHIVE_OWNER_EMAIL", o["manager"].email)
    assert o["client"].get(url).content == b"recover"
    o["outsider"].role = RoleEnum.admin; db.commit(); o["actor"][0] = o["outsider"]
    assert o["client"].get(url).status_code == 403


def test_invoice_upload_is_durable_private_and_keeps_revisions(operations, monkeypatch, tmp_path):
    from routes import ordini
    o = operations; db = o["db"]; c = o["client"]; o["actor"][0] = o["manager"]
    monkeypatch.setattr(ordini, "INVOICE_UPLOAD_DIR", tmp_path)
    order = PurchaseOrder(order_number="invoice-test")
    db.add(order); db.commit()
    url = f"/manager/ordini/{order.id}/fattura"
    for content in (b"first", b"second"):
        result = c.post(url, files={"invoice_file": ("facture.pdf", content, "application/pdf")}, follow_redirects=False)
        assert result.status_code == 303, result.text
    assert list(tmp_path.iterdir()) == []
    assert db.query(CloudAsset).filter_by(kind="invoice").count() == 2
    db.refresh(order)
    assert order.file_invoice.startswith("cloud:")
    assert c.get(url + "/allegato").content == b"second"
    assert "/fattura/allegato" in c.get(f"/manager/ordini/{order.id}").text
    o["actor"][0] = o["capo"]
    assert c.get(url + "/allegato").status_code == 403
    assert c.get("/static/uploads/invoices/old.pdf").status_code == 404


def test_native_backup_restores_sqlite_documents_and_order_links(operations, tmp_path):
    o = operations; db = o["db"]
    if db.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite restore exercised in the SQLite job")
    key = enqueue(db, "invoice", 1, "i.pdf", b"saved invoice")
    order = PurchaseOrder(order_number="backup", file_invoice="cloud:" + key)
    db.add(order); db.commit()
    bundle = make_bundle(db.get_bind(), tmp_path)
    restore = tmp_path / "isolated-restore"; restore.mkdir()
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(restore)
        assert json.loads(archive.read("manifest.json"))["database"] == "sqlite"
    with sqlite3.connect(restore / "database.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        pointer = connection.execute("SELECT file_invoice FROM purchase_orders WHERE order_number='backup'").fetchone()[0]
        assert connection.execute("SELECT payload FROM cloud_assets WHERE source_key=?", (pointer[6:],)).fetchone()[0] == b"saved invoice"
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3


def test_native_postgres_backup_is_valid_custom_dump(operations, tmp_path):
    o = operations
    if o["db"].get_bind().dialect.name != "postgresql":
        pytest.skip("PostgreSQL backup exercised in the PostgreSQL job")
    assert shutil.which("pg_dump") and shutil.which("pg_restore")
    enqueue(o["db"], "invoice", 1, "test.pdf", b"pg invoice"); o["db"].commit()
    bundle = make_bundle(o["db"].get_bind(), tmp_path)
    with zipfile.ZipFile(bundle) as archive:
        assert "database.dump" in archive.namelist()
    result = subprocess.run([shutil.which("pg_restore"), "--list", str(tmp_path / "database.dump")], capture_output=True, text=True)
    assert result.returncode == 0 and "cloud_assets" in result.stdout and "purchase_orders" in result.stdout
    assert not (tmp_path / ".pgpass").exists()


def test_backup_uses_separate_destination_and_reports_missing_sources(operations, tmp_path):
    o = operations; db = o["db"]
    if db.get_bind().dialect.name != "sqlite":
        pytest.skip("Native SQLite upload bundle test")
    stub = ArchiveStub()
    result = send_backup(factory(o), config(), stub)
    assert result["restore_tested"] is False and stub.uploads[0][0] == "private"
    assert db.query(CloudRun).filter_by(kind="backup").one().status == "verified"
    db.add(PurchaseOrder(order_number="missing-backup", file_invoice="uploads/invoices/not-there.pdf")); db.commit()
    with pytest.raises(CloudError, match="backup_missing_sources"):
        send_backup(factory(o), config(), stub)
    assert len(stub.uploads) == 1


@pytest.mark.parametrize("code,expected", [(401,"authentication_failed"), (403,"permission_denied"), (429,"throttled"), (503,"remote_unavailable"), (507,"storage_full")])
def test_graph_errors_are_safe_and_honor_retry_after(code, expected):
    response = httpx.Response(code, headers={"Retry-After": "180"}, json={"error": "NEVER-SHOW-THIS-SECRET"})
    with pytest.raises(CloudError) as error:
        GraphClient.checked(response)
    assert error.value.code == expected and error.value.retry_after == 180
    assert "NEVER" not in str(error.value)


def test_graph_validates_destination_and_prevents_backup_in_shared_library():
    calls = []
    def handle(request):
        calls.append(request)
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "secret-token", "expires_in": 3600})
        if request.url.path.endswith("/drives"):
            return httpx.Response(200, json={"value": [{"id": "docs", "name": "Documents"}]})
        return httpx.Response(200, json={"webUrl": "https://lentafrance.sharepoint.com/sites/gestionale-app"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        graph = GraphClient(config(), http)
        assert graph.check_destination() == "docs"
        graph.config.backup_drive_id = "docs"
        with pytest.raises(CloudError, match="backup_requires_separate_library"):
            graph.check_destination(backup=True)
        graph.config.drive_id = "foreign"
        with pytest.raises(CloudError, match="destination_mismatch"):
            graph.check_destination()
    assert sum("oauth2" in str(r.url) for r in calls) == 1


@pytest.mark.parametrize("url", ["http://lentafrance.sharepoint.com/x", "https://evil.example/x", "https://lentafrance.sharepoint.com.evil.example/x", "https://user@lentafrance.sharepoint.com/x"])
def test_transfer_urls_cannot_leak_credentials(url):
    with httpx.Client() as http:
        graph = GraphClient(config(), http)
        with pytest.raises(CloudError, match="unsafe_remote_url"):
            graph.safe_transfer_url(url)


def test_graph_chunked_upload_verifies_download_and_never_forwards_bearer(monkeypatch):
    content = b"x" * (CHUNK + 7)
    uploaded = bytearray(); puts = []; downloads = []
    def handle(request):
        url = str(request.url)
        if "oauth2" in url:
            return httpx.Response(200, json={"access_token": "secret-token"})
        if url.endswith("createUploadSession"):
            assert json.loads(request.content)["item"]["@microsoft.graph.conflictBehavior"] == "fail"
            return httpx.Response(200, json={"uploadUrl": "https://lentafrance.sharepoint.com/upload"})
        if url.endswith("/upload"):
            assert "authorization" not in request.headers
            puts.append(request.headers["Content-Range"])
            uploaded.extend(request.content)
            return httpx.Response(201, json={"id": "item", "size": len(content)}) if len(uploaded) == len(content) else httpx.Response(202, json={"nextExpectedRanges": [f"{len(uploaded)}-"]})
        if url.endswith("/content"):
            return httpx.Response(302, headers={"Location": "https://lentafrance.sharepoint.com/download"})
        if url.endswith("/download"):
            assert "authorization" not in request.headers
            downloads.append(True)
            return httpx.Response(200, content=bytes(uploaded))
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        graph = GraphClient(config(), http)
        monkeypatch.setattr(graph, "folder", lambda *a: "/drives/docs/items/folder")
        assert graph.upload("docs", ["Gestionale"], "test.pdf", io.BytesIO(content), len(content), hashlib.sha256(content).hexdigest()) == "item"
    assert bytes(uploaded) == content and len(puts) == 2 and downloads == [True]
    assert puts[0] == f"bytes 0-{CHUNK-1}/{len(content)}"


def test_existing_remote_file_is_verified_without_overwriting(monkeypatch):
    methods = []
    def handle(request):
        methods.append(request.method)
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=b"wrong")
        return httpx.Response(200, json={"id": "existing", "size": 5})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        graph = GraphClient(config(), http)
        monkeypatch.setattr(graph, "folder", lambda *a: "/drives/docs/root")
        with pytest.raises(CloudError, match="verification_failed"):
            graph.upload("docs", [], "same.pdf", io.BytesIO(b"right"), 5, hashlib.sha256(b"right").hexdigest())
    assert "PUT" not in methods and methods.count("POST") == 1


def test_folder_creation_recovers_a_concurrent_create():
    gets = 0
    def handle(request):
        nonlocal gets
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "t"})
        if request.method == "POST":
            assert json.loads(request.content)["@microsoft.graph.conflictBehavior"] == "fail"
            return httpx.Response(409)
        gets += 1
        return httpx.Response(404) if gets == 1 else httpx.Response(200, json={"id": "folder", "folder": {}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        graph = GraphClient(config(), http)
        assert graph.folder("docs", ["Gestionale"]) == "/drives/docs/items/folder"
