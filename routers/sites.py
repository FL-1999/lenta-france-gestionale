from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Site
from schemas import SiteCreate, SiteRead
from deps import (
    require_manager_or_admin,
    require_caposquadra_or_above,
    scope_sites_query,
    get_site_for_user,
)

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
    query = db.query(Site)
    query = scope_sites_query(query, user)
    return query.all()


@router.get("/{site_id}", response_model=SiteRead)
def get_site(
    site_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    return get_site_for_user(db, site_id, user)
