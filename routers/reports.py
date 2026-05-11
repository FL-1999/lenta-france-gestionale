from datetime import date as dt_date
from math import ceil
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_api, get_current_active_user_html
from database import get_db
from models import (
    Personale,
    PersonalePresenza,
    Report,
    ReportWorker,
    Role,
    RoleEnum,
    Site,
    User,
    UserRole,
)
from notifications import notify_new_report
from permissions import has_perm
from template_context import build_template_context, register_manager_badges
from utils.reports import report_man_hours, report_total_hours
from services.personale_profiles import ensure_user_personale_profile

router = APIRouter(
    prefix="",
    tags=["reports"],
)

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
templates.env.globals["report_total_hours"] = report_total_hours
templates.env.globals["report_man_hours"] = report_man_hours

REPORT_WORK_DAY_TYPE = "WORK"
DEFAULT_REPORT_WORKER_HOURS = 8.0


# ---------------------------
# SCHEMI Pydantic (v2)
# ---------------------------

class ReportBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt_date = Field(..., description="Data del rapportino")
    site_name_or_code: str = Field(..., description="Nome o codice cantiere")
    total_hours: float = Field(..., ge=0, description="Ore totali lavorate")
    workers_count: int = Field(..., ge=1, description="Totale personale (caposquadra incluso)")
    machines_used: Optional[str] = Field(
        default=None, description="Macchinari utilizzati (testo libero)"
    )
    activities: Optional[str] = Field(
        default=None, description="Descrizione attività svolte"
    )
    notes: Optional[str] = Field(
        default=None, description="Note aggiuntive"
    )


class ReportCreate(ReportBase):
    """Schema usato in input (creazione rapportino)."""
    site_id: Optional[int] = None
    workers: List["ReportWorkerIn"] = Field(default_factory=list)

class ReportWorkerIn(BaseModel):
    personale_id: int
    role_label: Optional[str] = None
    note: Optional[str] = None
    hours_worked: Optional[float] = Field(default=None, ge=0)
    day_type: Optional[str] = None


class ReportOut(ReportBase):
    """Schema usato in output (risposta API)."""
    id: int
    site_id: Optional[int] = None
    workers: List["ReportWorkerOut"] = Field(default_factory=list)
    created_by_email: Optional[str] = None
    created_by_role: Optional[str] = None


class ReportWorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    personale_id: int
    role_label: Optional[str] = None
    note: Optional[str] = None
    hours_worked: float
    day_type: str


ReportCreate.model_rebuild()
ReportOut.model_rebuild()

def ensure_capo_personale(db: Session, capo: User) -> Personale:
    """Restituisce/crea l'anagrafica personale collegata al caposquadra autenticato."""
    personale = ensure_user_personale_profile(
        db,
        capo,
        roles=[RoleEnum.caposquadra],
        create_personale_profile=True,
    )
    if personale is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Impossibile creare o associare il caposquadra al personale.",
        )
    return personale


def _with_auto_capo_worker(
    db: Session,
    current_user: User,
    report_in: ReportCreate,
) -> tuple[list[ReportWorkerIn], int]:
    workers = list(report_in.workers)
    if current_user.role == RoleEnum.caposquadra:
        capo_personale = ensure_capo_personale(db, current_user)
        capo_worker = next(
            (worker for worker in workers if worker.personale_id == capo_personale.id),
            None,
        )
        if capo_worker is None:
            workers.insert(
                0,
                ReportWorkerIn(
                    personale_id=capo_personale.id,
                    role_label="Caposquadra (tu)",
                    hours_worked=DEFAULT_REPORT_WORKER_HOURS,
                    day_type=REPORT_WORK_DAY_TYPE,
                ),
            )
        else:
            capo_worker.role_label = capo_worker.role_label or "Caposquadra (tu)"
            if capo_worker.hours_worked is None:
                capo_worker.hours_worked = DEFAULT_REPORT_WORKER_HOURS
            capo_worker.day_type = REPORT_WORK_DAY_TYPE
            workers = [
                capo_worker,
                *[worker for worker in workers if worker.personale_id != capo_personale.id],
            ]

    for worker in workers:
        if worker.hours_worked is None:
            worker.hours_worked = DEFAULT_REPORT_WORKER_HOURS
        worker.day_type = REPORT_WORK_DAY_TYPE

    return workers, len(workers)


def _ensure_requested_workers_count(report_in: ReportCreate, actual_count: int) -> None:
    if report_in.workers_count != actual_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Il totale personale deve corrispondere alle righe personale "
                "(caposquadra incluso)."
            ),
        )


def _validate_and_build_report_workers(
    db: Session,
    report_date: dt_date,
    site_id: int | None,
    total_hours: float,
    workers_count: int,
    workers_in: list[ReportWorkerIn],
    report_id: int | None = None,
) -> list[ReportWorker]:
    personale_ids = [w.personale_id for w in workers_in]
    if len(personale_ids) != len(set(personale_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Lo stesso operaio non può comparire due volte nello stesso rapportino.",
        )

    workers_map = {
        row.id: row
        for row in db.query(Personale)
        .filter(
            Personale.id.in_(personale_ids),
            Personale.attivo.is_(True),
        )
        .all()
    }
    if len(workers_map) != len(personale_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uno o più operai selezionati non esistono o non sono attivi.",
        )

    for worker_in in workers_in:
        conflict_query = db.query(PersonalePresenza).filter(
            PersonalePresenza.personale_id == worker_in.personale_id,
            PersonalePresenza.attendance_date == report_date,
            PersonalePresenza.site_id.isnot(None),
            PersonalePresenza.site_id != site_id,
        )
        if report_id is not None:
            conflict_query = conflict_query.filter(
                PersonalePresenza.report_id != report_id
            )
        conflict = conflict_query.first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "L'operaio selezionato risulta già assegnato a un altro cantiere "
                    "nello stesso giorno."
                ),
            )

    return [
        ReportWorker(
            personale_id=worker.personale_id,
            site_id=site_id,
            attendance_date=report_date,
            role_label=worker.role_label,
            note=worker.note,
            hours_worked=(
                worker.hours_worked
                if worker.hours_worked is not None
                else DEFAULT_REPORT_WORKER_HOURS
            ),
            day_type=REPORT_WORK_DAY_TYPE,
        )
        for worker in workers_in
    ]


def _sync_attendance_from_report(db: Session, report: Report) -> None:
    current_workers_by_personale = {worker.personale_id: worker for worker in report.workers}
    linked_presenze = (
        db.query(PersonalePresenza)
        .filter(PersonalePresenza.report_id == report.id)
        .all()
    )
    linked_by_personale = {pres.personale_id: pres for pres in linked_presenze}

    # upsert presenze correnti
    for worker in report.workers:
        presenza = linked_by_personale.get(worker.personale_id)
        if not presenza:
            presenza = (
                db.query(PersonalePresenza)
                .filter(
                    PersonalePresenza.personale_id == worker.personale_id,
                    PersonalePresenza.attendance_date == report.date,
                )
                .first()
            )
        if not presenza:
            presenza = PersonalePresenza(
                report_id=report.id,
                personale_id=worker.personale_id,
                attendance_date=report.date,
                site_id=report.site_id,
                status=REPORT_WORK_DAY_TYPE,
                hours=worker.hours_worked,
                note=worker.note,
            )
        else:
            presenza.report_id = report.id
            presenza.attendance_date = report.date
            presenza.site_id = report.site_id
            presenza.status = REPORT_WORK_DAY_TYPE
            presenza.hours = worker.hours_worked
            presenza.note = worker.note
        db.add(presenza)

    # cleanup presenze non più presenti nel rapportino
    for presenza in linked_presenze:
        if presenza.personale_id not in current_workers_by_personale:
            db.delete(presenza)


def _report_to_out(report: Report) -> ReportOut:
    return ReportOut(
        id=report.id,
        date=report.date,
        site_id=report.site_id,
        site_name_or_code=report.site_name_or_code,
        total_hours=report_total_hours(report),
        workers_count=report.workers_count,
        machines_used=report.machines_used,
        activities=report.activities,
        notes=report.notes,
        workers=[
            ReportWorkerOut.model_validate(worker)
            for worker in sorted(report.workers, key=lambda item: item.id or 0)
        ],
        created_by_email=report.created_by.email if report.created_by else None,
        created_by_role=(
            report.created_by.role.value
            if report.created_by and hasattr(report.created_by.role, "value")
            else None
        ),
    )


# ---------------------------
# ENDPOINTS
# ---------------------------

@router.post(
    "/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED
)
def create_report(
    report_in: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    """
    Crea un nuovo rapportino e lo salva nel database.

    Ruoli ammessi:
    - admin
    - manager
    - caposquadra
    """

    if current_user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per creare un rapportino.",
        )

    workers_in, workers_count = _with_auto_capo_worker(db, current_user, report_in)
    _ensure_requested_workers_count(report_in, workers_count)

    db_report = Report(
        date=report_in.date,
        site_id=report_in.site_id,
        site_name_or_code=report_in.site_name_or_code,
        total_hours=report_in.total_hours,
        workers_count=workers_count,
        machines_used=report_in.machines_used,
        activities=report_in.activities,
        notes=report_in.notes,
        created_by_id=current_user.id,
    )
    db_report.workers = _validate_and_build_report_workers(
        db=db,
        report_date=report_in.date,
        site_id=report_in.site_id,
        total_hours=report_in.total_hours,
        workers_count=workers_count,
        workers_in=workers_in,
        report_id=None,
    )

    db.add(db_report)
    db.flush()
    _sync_attendance_from_report(db, db_report)
    notify_new_report(db, db_report, current_user)
    db.commit()
    db.refresh(db_report)
    db.refresh(db_report, attribute_names=["workers", "created_by"])

    return _report_to_out(db_report)


@router.put("/reports/{report_id}", response_model=ReportOut)
def update_report(
    report_id: int,
    report_in: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    report = (
        db.query(Report)
        .options(joinedload(Report.workers), joinedload(Report.created_by))
        .filter(Report.id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapportino non trovato.")

    is_owner = report.created_by_id == current_user.id
    if not is_owner and current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non autorizzato.")

    workers_in, workers_count = _with_auto_capo_worker(db, current_user, report_in)
    _ensure_requested_workers_count(report_in, workers_count)

    report.date = report_in.date
    report.site_id = report_in.site_id
    report.site_name_or_code = report_in.site_name_or_code
    report.total_hours = report_in.total_hours
    report.workers_count = workers_count
    report.machines_used = report_in.machines_used
    report.activities = report_in.activities
    report.notes = report_in.notes
    report.workers = _validate_and_build_report_workers(
        db=db,
        report_date=report_in.date,
        site_id=report_in.site_id,
        total_hours=report_in.total_hours,
        workers_count=workers_count,
        workers_in=workers_in,
        report_id=report.id,
    )
    db.add(report)
    db.flush()
    _sync_attendance_from_report(db, report)
    db.commit()
    db.refresh(report)
    db.refresh(report, attribute_names=["workers", "created_by"])
    return _report_to_out(report)


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapportino non trovato.")

    is_owner = report.created_by_id == current_user.id
    if not is_owner and current_user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non autorizzato.")

    linked_presenze = (
        db.query(PersonalePresenza)
        .filter(PersonalePresenza.report_id == report.id)
        .all()
    )
    for presenza in linked_presenze:
        db.delete(presenza)
    db.delete(report)
    db.commit()
    return None


@router.get("/reports", response_model=List[ReportOut])
def list_reports_for_manager(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_api),
):
    """
    Lista rapportini.

    - Se sei admin/manager → vedi tutti i rapportini
    - Se sei caposquadra → vedi solo i tuoi
    """

    query = db.query(Report).options(joinedload(Report.workers), joinedload(Report.created_by))

    if current_user.role == RoleEnum.caposquadra:
        query = query.filter(Report.created_by_id == current_user.id)

    reports = query.order_by(Report.date.desc(), Report.id.desc()).all()

    return [_report_to_out(r) for r in reports]


@router.get("/manager/rapportini", include_in_schema=False)
def manager_reports_list(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    site_id: int | None = None,
    created_by: int | None = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    if not (has_perm(current_user, "manager.access") or has_perm(current_user, "reports.read_all")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non autorizzato")

    query = db.query(Report).options(joinedload(Report.workers))

    if start_date:
        try:
            parsed_start = dt_date.fromisoformat(start_date)
            query = query.filter(Report.date >= parsed_start)
        except ValueError:
            start_date = None

    if end_date:
        try:
            parsed_end = dt_date.fromisoformat(end_date)
            query = query.filter(Report.date <= parsed_end)
        except ValueError:
            end_date = None

    if site_id:
        query = query.filter(Report.site_id == site_id)

    if created_by:
        query = query.filter(Report.created_by_id == created_by)

    page = max(1, page)
    per_page = max(1, per_page)

    total_reports = query.count()
    total_pages = max(1, ceil(total_reports / per_page))
    offset_value = (page - 1) * per_page

    reports_page = (
        query.order_by(Report.date.desc(), Report.id.desc())
        .offset(offset_value)
        .limit(per_page)
        .all()
    )

    sites = db.query(Site).order_by(Site.name).all()
    capisquadra = (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).filter(Role.name == RoleEnum.caposquadra).distinct()
        .order_by(User.full_name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "manager/rapportini_list.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            reports=reports_page,
            report_total_hours=report_total_hours,
            report_man_hours=report_man_hours,
            page=page,
            total_pages=total_pages,
            filters={
                "start_date": start_date,
                "end_date": end_date,
                "site_id": site_id,
                "created_by": created_by,
            },
            sites=sites,
            caposquadra=capisquadra,
        ),
    )


@router.get("/manager/rapportini/{report_id}", include_in_schema=False)
def manager_report_detail(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    if not (has_perm(current_user, "manager.access") or has_perm(current_user, "reports.read_all")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non autorizzato")

    report = (
        db.query(Report)
        .options(
            joinedload(Report.created_by),
            joinedload(Report.site),
            joinedload(Report.workers).joinedload(ReportWorker.worker),
        )
        .filter(Report.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapportino non trovato")

    return templates.TemplateResponse(
        request,
        "manager/rapportino_detail.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            report=report,
            report_total_hours=report_total_hours,
            report_man_hours=report_man_hours,
        ),
    )
