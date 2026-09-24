"""Readable SharePoint paths. IDs are short disambiguators, hashes stay in the DB."""
from pathlib import PurePosixPath
import re
import unicodedata

from models import CloudAsset, Site


def safe_name(value, limit=100):
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\x00-\x1f\x7f"*:<>?/\\|#%]', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")[:limit].rstrip(" .")
    if not value or value.casefold() in {"con", "prn", "aux", "nul", ".lock", "desktop.ini"} or re.fullmatch(r"(?i)(com|lpt)[0-9]", value):
        return "Documento"
    return value.replace("_vti_", "-vti-").lstrip("~") or "Documento"


def legacy_filter():
    # Previous layout embeds the complete content hash in the filename.
    return CloudAsset.remote_path.contains("-" + CloudAsset.sha256 + "-")


def readable_location(db, asset):
    if asset.site_id:
        site = db.query(Site.code, Site.name).filter(Site.id == asset.site_id).first()
        title = " - ".join(x for x in (site.code, site.name) if x) if site else "Cantiere rimosso"
        # The short stable reference prevents collisions after sanitizing names.
        folder = f"{safe_name(title, 85)} [C{asset.site_id}]"
        # Once chosen, reuse a site's recorded folder even if its name changes.
        prior = db.query(CloudAsset.remote_path).filter(
            CloudAsset.site_id == asset.site_id, CloudAsset.remote_path.isnot(None),
            ~legacy_filter(), CloudAsset.status != "deleted",
        ).order_by(CloudAsset.id).first()
        if prior:
            components = prior.remote_path.split("/")
            if len(components) >= 4 and components[:2] == ["Gestionale", "Cantieri"] and components[2].endswith(f" [C{asset.site_id}]"):
                folder = components[2]
        parts = ["Gestionale", "Cantieri", folder]
    else:
        parts = ["Gestionale", "Acquisti"]
    reference = safe_name(asset.source_id, 25)
    if asset.kind == "plan":
        parts += ["Piante", f"Disegno {reference}"]
    elif asset.kind == "plan_preview":
        parts += ["Supporto gestionale", "Anteprime", f"Disegno {reference}"]
    else:
        parts += [{"document": "Documenti", "fiche_pdf": "Fiches", "dossier_pdf": "Dossier finali",
                   "invoice": "Fatture"}.get(asset.kind, "Esportazioni")]
    original = PurePosixPath(asset.filename.replace("\\", "/")).name
    suffix = re.sub(r"[^a-zA-Z0-9.]", "", PurePosixPath(original).suffix)[:12]
    stem = "Anteprima" if asset.kind == "plan_preview" else safe_name(PurePosixPath(original).stem, 100)
    return parts, f"{stem} - copia {asset.id}{suffix}"
