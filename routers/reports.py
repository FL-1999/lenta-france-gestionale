from datetime import date as dt_date
from math import ceil
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user, get_current_active_user_html
from database import get_db
from models import RoleEnum, Report, Site, User
from notifications import notify_new_report
from permissions import has_perm
from template_context import build_template_context, register_manager_badges

router = APIRouter(
    prefix="",
    tags=["reports"],
)

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)


# ---------------------------
# SCHEMI Pydantic (v2)
# ---------------------------

class ReportBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: dt_date = Field(..., description="Data del rapportino")
    site_name_or_code: str = Field(..., description="Nome o codice cantiere")
    total_hours: float = Field(..., ge=0, description="Ore totali lavorate")
    workers_count: int = Field(..., ge=0, description="Numero operai")
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
    pass


class ReportOut(ReportBase):
    """Schema usato in output (risposta API)."""
    id: int
    created_by_email: Optional[str] = None
    created_by_role: Optional[str] = None


# ---------------------------
# ENDPOINTS
# ---------------------------

@router.post(
    "/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED
)
def create_report(
    report_in: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
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

    db_report = Report(
        date=report_in.date,
        site_name_or_code=report_in.site_name_or_code,
        total_hours=report_in.total_hours,
        workers_count=report_in.workers_count,
        machines_used=report_in.machines_used,
        activities=report_in.activities,
        notes=report_in.notes,
        created_by_id=current_user.id,
    )

    db.add(db_report)
    db.flush()
    notify_new_report(db, db_report, current_user)
    db.commit()
    db.refresh(db_report)

    return ReportOut(
        id=db_report.id,
        date=db_report.date,
        site_name_or_code=db_report.site_name_or_code,
        total_hours=db_report.total_hours,
        workers_count=db_report.workers_count,
        machines_used=db_report.machines_used,
        activities=db_report.activities,
        notes=db_report.notes,
        created_by_email=current_user.email,
        created_by_role=(
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        ),
    )


@router.get("/reports", response_model=List[ReportOut])
def list_reports_for_manager(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Lista rapportini.

    - Se sei admin/manager → vedi tutti i rapportini
    - Se sei caposquadra → vedi solo i tuoi
    """

    query = db.query(Report)

    if current_user.role == RoleEnum.caposquadra:
        query = query.filter(Report.created_by_id == current_user.id)

    reports = query.order_by(Report.date.desc(), Report.id.desc()).all()

    result: List[ReportOut] = []
    for r in reports:
        result.append(
            ReportOut(
                id=r.id,
                date=r.date,
                site_name_or_code=r.site_name_or_code,
                total_hours=r.total_hours,
                workers_count=r.workers_count,
                machines_used=r.machines_used,
                activities=r.activities,
                notes=r.notes,
                created_by_email=r.created_by.email if r.created_by else None,
                created_by_role=(
                    r.created_by.role.value
                    if r.created_by and hasattr(r.created_by.role, "value")
                    else None
                ),
            )
        )

    return result


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

    query = db.query(Report)

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
        .filter(User.role == RoleEnum.caposquadra)
        .order_by(User.full_name)
        .all()
    )

    return templates.TemplateResponse(
        "manager/rapportini_list.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            reports=reports_page,
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
        .options(joinedload(Report.created_by), joinedload(Report.site))
        .filter(Report.id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapportino non trovato")

    return templates.TemplateResponse(
        "manager/rapportino_detail.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            report=report,
        ),
    )
