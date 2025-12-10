from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import DailyReport, Site
from schemas import DailyReportCreate, DailyReportRead
from deps import require_caposquadra_or_above

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/", response_model=DailyReportRead)
def create_report(
    report_in: DailyReportCreate,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    site = db.query(Site).filter(Site.id == report_in.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    report = DailyReport(
        site_id=report_in.site_id,
        author_id=user.id,
        date=report_in.date,
        weather=report_in.weather,
        num_workers=report_in.num_workers,
        hours_worked=report_in.hours_worked,
        notes=report_in.notes,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/site/{site_id}", response_model=list[DailyReportRead])
def list_reports_for_site(
    site_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    reports = db.query(DailyReport).filter(DailyReport.site_id == site_id).all()
    return reports