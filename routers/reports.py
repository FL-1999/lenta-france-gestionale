from datetime import date as dt_date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from database import get_db
from models import User, RoleEnum, Report
from auth import get_current_active_user

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
)


# ===========================
# SCHEMI Pydantic (v2)
# ===========================

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


# ===========================
# ENDPOINTS
# ===========================

@router.post("/", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
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


@router.get("/", response_model=List[ReportOut])
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
