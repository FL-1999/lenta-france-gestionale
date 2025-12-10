from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Site
from schemas import SiteCreate, SiteRead
from deps import require_manager_or_admin, require_caposquadra_or_above

router = APIRouter(prefix="/sites", tags=["sites"])


@router.post("/", response_model=SiteRead)
def create_site(
    site_in: SiteCreate,
    db: Session = Depends(get_db),
    user=Depends(require_manager_or_admin),
):
    site = Site(
        name=site_in.name,
        location=site_in.location,
        status=site_in.status,
        progress=site_in.progress,
        description=site_in.description,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


@router.get("/", response_model=list[SiteRead])
def list_sites(
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    return db.query(Site).all()


@router.get("/{site_id}", response_model=SiteRead)
def get_site(
    site_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")
    return site