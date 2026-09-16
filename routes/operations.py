from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, exists
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from auth import get_current_active_user_api
from audit_utils import log_audit_event
from database import get_db
from models import (Attrezzatura, DocumentVersion, Machine, MagazzinoRichiesta,
                    MagazzinoRichiestaStatusEnum, Personale, Report, ReportDraft,
                    ReportReview, ReportReviewEvent, ResourcePlan, RoleEnum, Site,
                    SiteDocument, SiteTask, TrasportoStatoEnum, TrasportoViaggio, User)
from template_context import build_template_context, register_manager_badges

router = APIRouter(prefix="/operazioni", tags=["operations"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)


def operator(user: User = Depends(get_current_active_user_api)) -> User:
    if user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(403, "Ruolo non autorizzato")
    return user


def manager(user: User = Depends(operator)) -> User:
    if user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(403, "Solo manager o admin")
    return user


def local_today() -> date:
    return datetime.now(ZoneInfo("Europe/Paris")).date()


def accessible_sites(db: Session, user: User):
    query = db.query(Site).filter(Site.is_active.is_(True))
    if user.role == RoleEnum.caposquadra:
        query = query.filter(Site.caposquadra_id == user.id)
    return query


def show(request, user, name, **context):
    return templates.TemplateResponse(request, name, build_template_context(request, user, **context))


class DraftInput(BaseModel):
    revision: int = Field(ge=0)
    payload: dict


@router.get("/bozza")
def get_draft(user: User = Depends(operator), db: Session = Depends(get_db)):
    row = db.get(ReportDraft, user.id)
    return {"revision": row.revision if row else 0,
            "payload": json.loads(row.payload) if row else None,
            "updated_at": row.updated_at.isoformat() + "Z" if row else None}


@router.put("/bozza")
def save_draft(body: DraftInput, user: User = Depends(operator), db: Session = Depends(get_db)):
    raw = json.dumps(body.payload, ensure_ascii=False)
    if len(raw.encode("utf-8")) > 100_000:
        raise HTTPException(413, "Bozza troppo grande")
    # Serialize first creation and updates too; a draft is private to its author.
    db.query(User).filter(User.id == user.id).with_for_update().first()
    row = db.get(ReportDraft, user.id)
    if body.revision != (row.revision if row else 0):
        raise HTTPException(409, "Bozza modificata in un'altra scheda. Ricarica prima di continuare.")
    updated_at = datetime.utcnow()
    next_revision = body.revision + 1
    if row is None:
        db.add(ReportDraft(user_id=user.id, revision=next_revision, payload=raw, updated_at=updated_at))
    else:
        changed = db.query(ReportDraft).filter_by(user_id=user.id, revision=body.revision).update(
            {"payload": raw, "revision": next_revision, "updated_at": updated_at}, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "Bozza modificata in un'altra scheda")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Bozza modificata in un'altra scheda")
    return {"revision": next_revision, "updated_at": updated_at.isoformat() + "Z"}


@router.delete("/bozza")
def delete_draft(revision: int, user: User = Depends(operator), db: Session = Depends(get_db)):
    db.query(User).filter(User.id == user.id).with_for_update().first()
    row = db.get(ReportDraft, user.id)
    if row and row.revision != revision:
        raise HTTPException(409, "Bozza modificata in un'altra scheda")
    if row:
        changed = db.query(ReportDraft).filter_by(user_id=user.id, revision=revision).update(
            {"payload": "null", "revision": revision + 1}, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "Bozza modificata in un'altra scheda")
        db.commit()
    return {"ok": True, "revision": revision + 1 if row else 0}


@router.get("/ultimo-rapportino")
def previous_report(site_id: int, before: date, user: User = Depends(operator), db: Session = Depends(get_db)):
    if not accessible_sites(db, user).filter(Site.id == site_id).first():
        raise HTTPException(403, "Cantiere non accessibile")
    report = db.query(Report).filter(Report.site_id == site_id, Report.created_by_id == user.id,
                                    Report.date < before).order_by(Report.date.desc(), Report.id.desc()).first()
    if not report:
        raise HTTPException(404, "Nessun tuo rapportino precedente per questo cantiere")
    return {"date": report.date.isoformat(), "fields": {"ore_totali": report.total_hours,
            "macchinari": report.machines_used or "", "attivita": report.activities or "", "note": report.notes or ""},
            "workers": [{"personale_id": w.personale_id, "hours_worked": w.hours_worked,
                         "role_label": w.role_label or "", "note": w.note or ""} for w in report.workers]}


@router.get("")
def today_page(request: Request, user: User = Depends(operator), db: Session = Depends(get_db)):
    today = local_today()
    sites = accessible_sites(db, user).order_by(Site.name).all()
    ids = [s.id for s in sites]
    tasks = db.query(SiteTask).filter(SiteTask.site_id.in_(ids), SiteTask.completed.is_(False),
                                     SiteTask.due_date <= today).order_by(SiteTask.due_date).limit(50).all()
    reports = db.query(Report).filter(Report.site_id.in_(ids), Report.date == today)
    if user.role == RoleEnum.caposquadra:
        reports = reports.filter(Report.created_by_id == user.id)
    recorded_ids = {r.site_id for r in reports.all()}
    # Absence of a record is shown neutrally, not as a missed obligation.
    without_report = [s for s in sites if s.id not in recorded_ids]
    reviews = db.query(Report, ReportReview).outerjoin(ReportReview, ReportReview.report_id == Report.id)
    if user.role == RoleEnum.caposquadra:
        reviews = reviews.filter(Report.created_by_id == user.id, ReportReview.status == "changes_requested")
    else:
        reviews = reviews.filter(or_(ReportReview.status.is_(None), ReportReview.status == "submitted"))
    review_rows = reviews.order_by(Report.date.desc(), Report.id.desc()).limit(30).all()
    trips, warehouse_count, expiring_docs = [], 0, []
    if user.role != RoleEnum.caposquadra:
        trips = db.query(TrasportoViaggio).filter(TrasportoViaggio.data_partenza <= today,
                    TrasportoViaggio.stato != TrasportoStatoEnum.completato).order_by(TrasportoViaggio.data_partenza).limit(30).all()
        warehouse_count = db.query(MagazzinoRichiesta).filter(
            MagazzinoRichiesta.stato.in_([MagazzinoRichiestaStatusEnum.in_attesa, MagazzinoRichiestaStatusEnum.parziale])).count()
        from sqlalchemy.orm import aliased
        newer = aliased(DocumentVersion)
        expiring_docs = db.query(DocumentVersion, SiteDocument).join(
            SiteDocument, SiteDocument.id == DocumentVersion.document_id).options(defer(SiteDocument.data)).filter(
                SiteDocument.site_id.in_(ids), DocumentVersion.expires_on <= today + timedelta(days=30),
                ~exists().where(newer.root_id == DocumentVersion.root_id, newer.number > DocumentVersion.number)
            ).order_by(DocumentVersion.expires_on).limit(30).all()
    draft = db.get(ReportDraft, user.id)
    return show(request, user, "operations/today.html", today=today, tasks=tasks,
                without_report=without_report, review_rows=review_rows, trips=trips,
                warehouse_count=warehouse_count, draft=draft, expiring_docs=expiring_docs)


def get_review_report(db, report_id, user, lock=False):
    query = db.query(Report).filter(Report.id == report_id)
    if lock:
        query = query.with_for_update()
    report = query.first()
    if not report:
        raise HTTPException(404, "Rapportino non trovato")
    if user.role == RoleEnum.caposquadra and report.created_by_id != user.id:
        raise HTTPException(403, "Non autorizzato")
    return report


@router.get("/rapportini/{report_id}")
def review_page(report_id: int, request: Request, user: User = Depends(operator), db: Session = Depends(get_db)):
    report = get_review_report(db, report_id, user)
    review = db.get(ReportReview, report_id)
    events = db.query(ReportReviewEvent, User).join(User, User.id == ReportReviewEvent.user_id).filter(
        ReportReviewEvent.report_id == report_id).order_by(ReportReviewEvent.id.desc()).all()
    payload = {"date": report.date.isoformat(), "site_id": report.site_id,
               "site_name_or_code": report.site_name_or_code, "workers_count": report.workers_count,
               "total_hours": report.total_hours, "review_version": review.version if review else 0,
               "workers": [{"personale_id": worker.personale_id, "hours_worked": worker.hours_worked,
                            "role_label": worker.role_label, "note": worker.note, "day_type": worker.day_type}
                           for worker in report.workers]}
    return show(request, user, "operations/review.html", report=report, review=review, events=events, edit_payload=payload)


@router.post("/rapportini/{report_id}/stato")
def review_report(report_id: int, action: str = Form(...), version: int = Form(...), note: str = Form(""),
                  user: User = Depends(operator), db: Session = Depends(get_db)):
    report = get_review_report(db, report_id, user, lock=True)
    review = db.get(ReportReview, report_id)
    if version != (review.version if review else 0):
        raise HTTPException(409, "Rapportino modificato: ricarica la pagina")
    current = review.status if review else "submitted"
    allowed = {"submitted": {"approved", "changes_requested"}, "approved": {"changes_requested"},
               "changes_requested": {"submitted"}}
    if action not in allowed.get(current, set()):
        raise HTTPException(409, "Passaggio di stato non consentito")
    if action != "submitted" and user.role == RoleEnum.caposquadra:
        raise HTTPException(403, "Solo manager o admin possono verificare")
    if action == "changes_requested" and not note.strip():
        raise HTTPException(422, "Indica la correzione richiesta")
    if len(note) > 3000:
        raise HTTPException(422, "Nota troppo lunga")
    values = {"status": action, "note": note.strip() or None, "version": version + 1,
              "updated_at": datetime.utcnow(), "updated_by_id": user.id}
    if review is None:
        db.add(ReportReview(report_id=report.id, **values))
    elif db.query(ReportReview).filter_by(report_id=report.id, version=version).update(values, synchronize_session=False) != 1:
        db.rollback()
        raise HTTPException(409, "Rapportino modificato: ricarica la pagina")
    db.add(ReportReviewEvent(report_id=report.id, status=action, user_id=user.id, note=values["note"]))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Rapportino modificato: ricarica la pagina")

    return RedirectResponse(f"/operazioni/rapportini/{report.id}", status_code=303)


def guard_report_edit(db, report, user):
    review = db.get(ReportReview, report.id)
    if review and review.status == "approved":
        raise HTTPException(409, "Rapportino validato: richiedere una correzione prima di modificarlo")


def track_report_edit(db, report, user):
    review = db.get(ReportReview, report.id)
    if not review:
        db.add(ReportReview(report_id=report.id, status="submitted", version=1,
                            updated_at=datetime.utcnow(), updated_by_id=user.id))
    else:
        version = review.version
        changed = db.query(ReportReview).filter_by(report_id=report.id, version=version).filter(
            ReportReview.status != "approved").update(
                {"version": version + 1, "updated_at": datetime.utcnow(), "updated_by_id": user.id}, synchronize_session=False)
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "Rapportino modificato o validato: ricarica la pagina")
    db.add(ReportReviewEvent(report_id=report.id, status="edited", user_id=user.id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Rapportino modificato: ricarica la pagina")


RESOURCE_MODELS = {"person": Personale, "machine": Machine, "equipment": Attrezzatura}


def resource_label(kind, row):
    if kind == "person":
        return f"{row.cognome} {row.nome}".strip()
    return str(getattr(row, "name", None) or getattr(row, "nome", None) or getattr(row, "codice", None) or row.id)


@router.get("/pianificazione")
def planning_page(request: Request, week: date | None = None, user: User = Depends(operator), db: Session = Depends(get_db)):
    start = week or local_today()
    start -= timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    sites = accessible_sites(db, user).order_by(Site.name).all()
    query = db.query(ResourcePlan, Site).join(Site, Site.id == ResourcePlan.site_id).filter(ResourcePlan.day.between(start, end))
    if user.role == RoleEnum.caposquadra:
        query = query.filter(Site.caposquadra_id == user.id)
    rows = query.order_by(ResourcePlan.day, Site.name, ResourcePlan.resource_label).all()
    resources = []
    if user.role != RoleEnum.caposquadra:
        for kind, model in RESOURCE_MODELS.items():
            q = db.query(model)
            if kind == "person":
                q = q.filter(Personale.attivo.is_(True))
            elif kind == "machine":
                q = q.filter(Machine.is_active.is_(True))
            resources.extend({"value": f"{kind}:{r.id}", "label": resource_label(kind, r), "kind": kind} for r in q.all())
    trips = db.query(TrasportoViaggio).filter(TrasportoViaggio.data_partenza.between(start, end)).order_by(TrasportoViaggio.data_partenza).all() if user.role != RoleEnum.caposquadra else []
    return show(request, user, "operations/planning.html", start=start, end=end, rows=rows,
                previous=start-timedelta(days=7), following=start+timedelta(days=7), sites=sites, resources=resources, trips=trips)


@router.post("/pianificazione")
def add_plan(day: date = Form(...), site_id: int = Form(...), resource: str = Form(...), note: str = Form(""),
             user: User = Depends(manager), db: Session = Depends(get_db)):
    try:
        kind, raw_id = resource.split(":")
        model, resource_id = RESOURCE_MODELS[kind], int(raw_id)
    except (ValueError, KeyError):
        raise HTTPException(422, "Risorsa non valida")
    if not accessible_sites(db, user).filter(Site.id == site_id).first():
        raise HTTPException(422, "Cantiere non attivo")
    row = db.query(model).filter(model.id == resource_id).with_for_update().first()
    if not row or (kind == "person" and not row.attivo) or (kind == "machine" and not row.is_active):
        raise HTTPException(422, "Risorsa non disponibile")
    if len(note) > 1000:
        raise HTTPException(422, "Nota troppo lunga")
    plan = ResourcePlan(day=day, site_id=site_id, resource_type=kind, resource_id=resource_id,
                        resource_label=resource_label(kind, row), created_by_id=user.id, note=note.strip() or None)
    db.add(plan)
    try:
        db.flush()
        log_audit_event(db, user, "PLAN_CREATED", "resource_plan", plan.id, {"day": str(day), "site_id": site_id})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Risorsa già pianificata quel giorno. Rimuovi o correggi l'assegnazione esistente.")
    return RedirectResponse(f"/operazioni/pianificazione?week={day}", status_code=303)


@router.post("/pianificazione/{plan_id}/elimina")
def delete_plan(plan_id: int, user: User = Depends(manager), db: Session = Depends(get_db)):
    row = db.get(ResourcePlan, plan_id)
    if not row:
        raise HTTPException(404, "Assegnazione non trovata")
    day = row.day
    log_audit_event(db, user, "PLAN_DELETED", "resource_plan", row.id,
                    {"day": str(day), "site_id": row.site_id, "resource": row.resource_label})
    db.delete(row)
    db.commit()
    return RedirectResponse(f"/operazioni/pianificazione?week={day}", status_code=303)


def document_family(db, doc_id, lock=False):
    version = db.get(DocumentVersion, doc_id)
    root_id = version.root_id if version else doc_id
    query = db.query(SiteDocument).options(defer(SiteDocument.data)).filter(SiteDocument.id == root_id)
    root = (query.with_for_update() if lock else query).first()
    if not root:
        raise HTTPException(404, "Documento non trovato")
    versions = db.query(DocumentVersion, SiteDocument).join(SiteDocument, SiteDocument.id == DocumentVersion.document_id).options(
        defer(SiteDocument.data)).filter(DocumentVersion.root_id == root.id).order_by(DocumentVersion.number.desc()).all()
    return root, versions


@router.get("/documenti/{doc_id}")
def document_page(doc_id: int, request: Request, user: User = Depends(manager), db: Session = Depends(get_db)):
    root, versions = document_family(db, doc_id)
    current = versions[0][1] if versions else root
    return show(request, user, "operations/documents.html", root=root, versions=versions, current=current, today=local_today())


@router.post("/documenti/{doc_id}/revisione")
async def upload_revision(doc_id: int, file: UploadFile = File(...), current_id: int = Form(...),
                          expires_on: str = Form(""), user: User = Depends(manager), db: Session = Depends(get_db)):
    # Bound the read before acquiring a database lock.
    content = await file.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(422, "File vuoto o superiore a 20 MB")
    try:
        expiry = date.fromisoformat(expires_on) if expires_on else None
    except ValueError:
        raise HTTPException(422, "Scadenza non valida")
    root, versions = document_family(db, doc_id, lock=True)
    latest_id = versions[0][1].id if versions else root.id
    if current_id != latest_id:
        raise HTTPException(409, "Esiste una revisione più recente: ricarica la pagina")
    document = SiteDocument(site_id=root.site_id, filename=(file.filename or "documento")[:300],
                           content_type=file.content_type, size_bytes=len(content), category=root.category,
                           description=root.description, data=content, uploaded_by_id=user.id)
    db.add(document)
    db.flush()
    number = versions[0][0].number + 1 if versions else 2
    db.add(DocumentVersion(document_id=document.id, root_id=root.id, number=number, expires_on=expiry))
    log_audit_event(db, user, "DOCUMENT_REVISION", "site_document", document.id, {"root_id": root.id, "revision": number})
    db.commit()
    return RedirectResponse(f"/operazioni/documenti/{root.id}", status_code=303)
