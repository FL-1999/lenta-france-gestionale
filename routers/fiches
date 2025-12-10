from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Fiche, StratigraphyLayer, Site, Machine
from schemas import FicheCreate, FicheRead
from deps import require_caposquadra_or_above

router = APIRouter(prefix="/fiches", tags=["fiches"])


@router.post("/", response_model=FicheRead)
def create_fiche(
    fiche_in: FicheCreate,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    site = db.query(Site).filter(Site.id == fiche_in.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    if fiche_in.machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == fiche_in.machine_id).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Macchinario non trovato")

    fiche = Fiche(
        site_id=fiche_in.site_id,
        machine_id=fiche_in.machine_id if fiche_in.machine_id else None,
        type=fiche_in.type,
        panel_number=fiche_in.panel_number,
        diameter_mm=fiche_in.diameter_mm,
        total_depth_m=fiche_in.total_depth_m,
        paratia_depth_m=fiche_in.paratia_depth_m,
        paratia_width_m=fiche_in.paratia_width_m,
        dig_date=fiche_in.dig_date,
        cast_date=fiche_in.cast_date,
    )
    db.add(fiche)
    db.commit()
    db.refresh(fiche)

    for layer_in in fiche_in.layers:
        layer = StratigraphyLayer(
            fiche_id=fiche.id,
            from_m=layer_in.from_m,
            to_m=layer_in.to_m,
            description=layer_in.description,
        )
        db.add(layer)

    db.commit()
    db.refresh(fiche)
    return fiche


@router.get("/site/{site_id}", response_model=list[FicheRead])
def list_fiches_for_site(
    site_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_caposquadra_or_above),
):
    fiches = db.query(Fiche).filter(Fiche.site_id == site_id).all()
    return fiches