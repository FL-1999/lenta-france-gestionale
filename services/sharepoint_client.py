"""App-only Microsoft Graph bridge. No credentials or Graph bodies in exceptions."""
from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import logging
import os
import re
import time
from urllib.parse import quote, urlsplit

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK = 10 * 320 * 1024
_PRIVATE_HTTP = ContextVar("sharepoint_private_http", default=False)


class _PrivateHttpFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_HTTP.get()


# HTTPX logs full request URLs at INFO, including preauthenticated query strings.
# Keep unrelated HTTP logs, but suppress transport details inside this adapter.
for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger_name).addFilter(_PrivateHttpFilter())


@contextmanager
def private_http():
    token = _PRIVATE_HTTP.set(True)
    try:
        yield
    finally:
        _PRIVATE_HTTP.reset(token)


class CloudError(Exception):
    def __init__(self, code, retry_after=60):
        self.code = code
        self.retry_after = min(max(int(retry_after), 60), 86400)
        super().__init__(code)


@dataclass
class SharePointConfig:
    tenant: str = ""
    client_id: str = ""
    secret: str = field(default="", repr=False)
    site_id: str = ""
    drive_id: str = ""
    hostname: str = "lentafrance.sharepoint.com"
    enabled: bool = False
    backup_site_id: str = ""
    backup_drive_id: str = ""
    backup_access_confirmed: bool = False

    @classmethod
    def from_env(cls):
        return cls(tenant=os.getenv("SHAREPOINT_TENANT_ID", "").strip(),
            client_id=os.getenv("SHAREPOINT_CLIENT_ID", "").strip(),
            secret=os.getenv("SHAREPOINT_CLIENT_SECRET", ""),
            site_id=os.getenv("SHAREPOINT_SITE_ID", "").strip(),
            drive_id=os.getenv("SHAREPOINT_DRIVE_ID", "").strip(),
            hostname=os.getenv("SHAREPOINT_HOSTNAME", "lentafrance.sharepoint.com").strip(),
            enabled=os.getenv("SHAREPOINT_SYNC_ENABLED", "").lower() == "true",
            backup_site_id=os.getenv("SHAREPOINT_BACKUP_SITE_ID", "").strip(),
            backup_drive_id=os.getenv("SHAREPOINT_BACKUP_DRIVE_ID", "").strip(),
            backup_access_confirmed=os.getenv("SHAREPOINT_BACKUP_ACCESS_CONFIRMED", "").lower() == "true")

    def missing(self):
        return [name for name, value in [("SHAREPOINT_TENANT_ID", self.tenant),
            ("SHAREPOINT_CLIENT_ID", self.client_id), ("SHAREPOINT_CLIENT_SECRET", self.secret),
            ("SHAREPOINT_SITE_ID", self.site_id), ("SHAREPOINT_DRIVE_ID", self.drive_id)] if not value]

    def validate(self):
        if self.missing():
            raise CloudError("configuration_missing")
        guid = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        if not re.fullmatch(guid, self.tenant) or not re.fullmatch(guid, self.client_id):
            raise CloudError("configuration_invalid")
        if not re.fullmatch(r"[a-z0-9-]+\.sharepoint\.com", self.hostname):
            raise CloudError("configuration_invalid")


class GraphClient:
    def __init__(self, config, http=None):
        config.validate()
        self.config = config
        self.http = http or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        self._owns_http = http is None
        self.token = None
        self.expires = 0

    def close(self):
        if self._owns_http:
            self.http.close()

    @staticmethod
    def checked(response, allowed=()):
        if response.status_code in allowed or 200 <= response.status_code < 300:
            return response
        code = {401: "authentication_failed", 403: "permission_denied", 404: "not_found",
                409: "conflict", 429: "throttled", 507: "storage_full"}.get(response.status_code, "remote_unavailable")
        retry = response.headers.get("Retry-After", "60")
        raise CloudError(code, int(retry) if retry.isdigit() else 60)

    def request(self, method, url, **kwargs):
        try:
            with private_http():
                return self.http.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise CloudError("network_error") from None

    def access_token(self):
        if not self.token or time.monotonic() >= self.expires:
            result = self.checked(self.request("POST", f"https://login.microsoftonline.com/{self.config.tenant}/oauth2/v2.0/token",
                data={"client_id": self.config.client_id, "client_secret": self.config.secret,
                      "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"})).json()
            self.token = result.get("access_token")
            if not self.token:
                raise CloudError("authentication_failed")
            self.expires = time.monotonic() + max(int(result.get("expires_in", 3600)) - 120, 0)
        return self.token

    def graph(self, method, path, allowed=(), **kwargs):
        headers = {**kwargs.pop("headers", {}), "Authorization": "Bearer " + self.access_token()}
        return self.checked(self.request(method, GRAPH + path, headers=headers, **kwargs), allowed)

    def check_destination(self, backup=False):
        site = self.config.backup_site_id if backup else self.config.site_id
        drive = self.config.backup_drive_id if backup else self.config.drive_id
        if not site or not drive or (backup and not self.config.backup_access_confirmed):
            raise CloudError("backup_destination_not_approved" if backup else "configuration_missing")
        if backup and drive == self.config.drive_id:
            raise CloudError("backup_requires_separate_library")
        site_info = self.graph("GET", f"/sites/{quote(site, safe=',')}").json()
        if urlsplit(site_info.get("webUrl", "")).hostname != self.config.hostname:
            raise CloudError("destination_mismatch")
        path = f"/sites/{quote(site, safe=',')}/drives?$select=id,name"
        found = False
        while path:
            result = self.graph("GET", path).json()
            found = found or any(d.get("id") == drive for d in result.get("value", []))
            link = result.get("@odata.nextLink")
            if link and not link.startswith(GRAPH + "/"):
                raise CloudError("unsafe_remote_url")
            path = link[len(GRAPH):] if link else None
        if not found:
            raise CloudError("destination_mismatch")
        return drive

    def folder(self, drive, parts):
        base = f"/drives/{quote(drive, safe='') }"
        parent = "root"
        for name in parts:
            path = f"{base}/{parent}:/{quote(name, safe='')}"
            result = self.graph("GET", path, allowed=(404,))
            if result.status_code == 404:
                result = self.graph("POST", f"{base}/{parent}/children", allowed=(409,),
                    json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
                if result.status_code == 409:
                    result = self.graph("GET", path)
            item = result.json()
            if "folder" not in item:
                raise CloudError("destination_conflict")
            parent = "items/" + quote(item["id"], safe="")
        return base + "/" + parent

    def safe_transfer_url(self, url):
        parsed = urlsplit(url)
        # Graph-provided SharePoint upload/download URLs are preauthenticated.
        # Never send the Graph bearer token to them or follow another redirect.
        if parsed.scheme != "https" or parsed.hostname != self.config.hostname or parsed.port not in (None, 443) or parsed.username:
            raise CloudError("unsafe_remote_url")
        return url

    def verify(self, drive, item_id, expected_hash, size):
        path = f"/drives/{quote(drive, safe='')}/items/{quote(item_id, safe='')}/content"
        response = self.graph("GET", path, allowed=(302, 303, 307))
        digest = hashlib.sha256()
        count = 0
        if response.status_code in (302, 303, 307):
            url = self.safe_transfer_url(response.headers.get("location", ""))
            try:
                with private_http(), self.http.stream("GET", url) as stream:
                    self.checked(stream)
                    for chunk in stream.iter_bytes():
                        count += len(chunk)
                        if count > size:
                            raise CloudError("verification_failed")
                        digest.update(chunk)
            except httpx.HTTPError:
                raise CloudError("network_error") from None
        else:
            count = len(response.content)
            digest.update(response.content)
        if count != size or digest.hexdigest() != expected_hash:
            raise CloudError("verification_failed")

    def purge_archive_copy(self, drive, item_id, remote_path, sha256, size):
        """Permanently remove only the exact archived file, never a folder.

        Missing known IDs are ambiguous (the file may be in the remote recycle
        bin). Preserve the local recovery copy and require investigation.
        """
        base = f"/drives/{quote(drive, safe='')}"
        if item_id:
            path = f"{base}/items/{quote(item_id, safe='')}"
        elif remote_path and remote_path.startswith("Gestionale/"):
            path = f"{base}/root:/{quote(remote_path, safe='/')}"
        else:
            raise CloudError("archive_destination_unknown")
        response = self.graph("GET", path, allowed=(404,))
        if response.status_code == 404:
            if item_id:
                raise CloudError("remote_copy_missing")
            # No completed item was ever recorded at this attempted path.
            return
        item = response.json()
        if "file" not in item or "folder" in item or not item.get("id") or not item.get("eTag"):
            raise CloudError("archive_remote_conflict")
        if item.get("size") != size:
            raise CloudError("archive_remote_conflict")
        self.verify(drive, item["id"], sha256, size)
        response = self.graph("POST", f"{base}/items/{quote(item['id'], safe='')}/permanentDelete",
                             headers={"If-Match": item["eTag"]})
        if response.status_code != 204:
            raise CloudError("remote_delete_unconfirmed")

    def upload(self, drive, parts, filename, fileobj, size, sha256):
        parent = self.folder(drive, parts)
        path = f"{parent}:/{quote(filename, safe='')}"
        existing = self.graph("GET", path, allowed=(404,))
        if existing.status_code == 200:
            item = existing.json()
        else:
            # Sessions use conflict=fail: retries cannot overwrite a foreign file.
            result = self.graph("POST", path + ":/createUploadSession", json={
                "item": {"@microsoft.graph.conflictBehavior": "fail", "name": filename}}).json()
            upload_url = self.safe_transfer_url(result.get("uploadUrl", ""))
            fileobj.seek(0)
            offset = 0
            item = None
            while offset < size:
                chunk = fileobj.read(min(CHUNK, size - offset))
                if not chunk:
                    raise CloudError("local_file_changed")
                end = offset + len(chunk) - 1
                result = self.checked(self.request("PUT", upload_url, content=chunk, headers={
                    "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{size}"}))
                offset = end + 1
                if result.status_code in (200, 201):
                    item = result.json()
                elif result.status_code != 202:
                    raise CloudError("upload_incomplete")
            if not item or not item.get("id"):
                raise CloudError("upload_incomplete")
        if item.get("size") != size:
            raise CloudError("verification_failed")
        self.verify(drive, item["id"], sha256, size)
        return item["id"]
