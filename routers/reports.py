from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User, RoleEnum
from auth import get_current_active_user

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
)


# ===========================
# SCHEMI Pydantic
# ===========================

class ReportCreate(BaseModel):
    date: date = Field(..., description="Data del rapportino")
    site_name_or_code: str = Field(..., description="Nome o codice cantiere")
    total_hours: float = Field(..., ge=0, description="Ore totali lavorate")
    workers_count: int = Field(..., ge=0, description="Numero operai")
    machines_used: str | None = Field(
        default=None, description="Macchinari utilizzati (testo libero)"
    )
    activities: str | None = Field(
        default=None, description="Descrizione attività svolte"
    )
    notes: str | None = Field(
        default=None, description="Note aggiuntive"
    )


class ReportOut(ReportCreate):
    id: int | None = None
    created_by_email: str | None = None
    created_by_role: str | None = None


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
    Crea un nuovo rapportino.

    👉 Per ora NON salviamo nel DB, ma:
       - validiamo i dati
       - controlliamo che l'utente sia autenticato
       - ritorniamo i dati ricevuti + info sull'utente

    In un secondo momento potremo:
       - creare un modello SQLAlchemy Report nel file models.py
       - salvare davvero questi dati nel database
    """

    # Esempio di controllo sui ruoli (puoi modificarlo):
    if current_user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per creare un rapportino.",
        )

    # Qui in futuro potrai creare un oggetto Report del tuo modello SQLAlchemy
    # e salvarlo nel DB. Adesso costruiamo solo un oggetto di risposta.
    report_out = ReportOut(
        id=None,  # quando avrai il DB potrai mettere l'id reale
        date=report_in.date,
        site_name_or_code=report_in.site_name_or_code,
        total_hours=report_in.total_hours,
        workers_count=report_in.workers_count,
        machines_used=report_in.machines_used,
        activities=report_in.activities,
        notes=report_in.notes,
        created_by_email=current_user.email,
        created_by_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
    )

    return report_out


@router.get("/demo", response_model=List[ReportOut])
def list_reports_demo(
    current_user: User = Depends(get_current_active_user),
):
    """
    Endpoint di demo: restituisce una lista finta di rapportini.

    Serve solo per testare rapidamente il frontend o l'autenticazione.
    NON legge dal database.
    """
    demo = [
        ReportOut(
            id=1,
            date=date.today(),
            site_name_or_code="CANTIERE-001",
            total_hours=8.0,
            workers_count=3,
            machines_used="Escavatore, Furgone",
            activities="Scavo trincea, trasporto materiale",
            notes="Nessun problema",
            created_by_email=current_user.email,
            created_by_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        )
    ]
    return demo
