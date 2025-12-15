from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user
from database import get_db
from models import Fiche, FicheTypeEnum, Site, Machine, User
from schemas import FicheCreate, FicheRead, FicheListItem

router = APIRouter(prefix="/fiches", tags=["fiches"])


@router.get("/", response_model=list[FicheListItem])
def list_fiches(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    site_id: Optional[int] = None,
    fiche_type: Optional[FicheTypeEnum] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(Fiche).join(Site).outerjoin(Machine).join(User)

    if from_date:
        query = query.filter(Fiche.date >= from_date)
    if to_date:
        query = query.filter(Fiche.date <= to_date)
    if site_id:
        query = query.filter(Fiche.site_id == site_id)
    if fiche_type:
        query = query.filter(Fiche.fiche_type == fiche_type)

    fiches = query.order_by(Fiche.date.desc(), Fiche.id.desc()).all()

    return [
        FicheListItem(
            id=fiche.id,
            date=fiche.date,
            site_name=fiche.site.name if fiche.site else "",
            machine_name=fiche.machine.name if fiche.machine else None,
            fiche_type=fiche.fiche_type,
            operator=fiche.operator,
            hours=fiche.hours,
            tipologia_scavo=fiche.tipologia_scavo,
            stratigrafia=fiche.stratigrafia,
            materiale=fiche.materiale,
            profondita_totale=fiche.profondita_totale,
            diametro_palo=fiche.diametro_palo,
            larghezza_pannello=fiche.larghezza_pannello,
            altezza_pannello=fiche.altezza_pannello,
            created_by_name=fiche.created_by.full_name or fiche.created_by.email,
        )
        for fiche in fiches
    ]


@router.get("/{fiche_id}", response_model=FicheRead)
def get_fiche_detail(
    fiche_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    fiche = (
        db.query(Fiche)
        .options(
            joinedload(Fiche.site),
            joinedload(Fiche.machine),
            joinedload(Fiche.created_by),
        )
        .filter(Fiche.id == fiche_id)
        .first()
    )

    if not fiche:
        raise HTTPException(status_code=404, detail="Fiche non trovata")

    return FicheRead(
        id=fiche.id,
        date=fiche.date,
        site_id=fiche.site_id,
        machine_id=fiche.machine_id,
        fiche_type=fiche.fiche_type,
        description=fiche.description,
        operator=fiche.operator,
        hours=fiche.hours,
        notes=fiche.notes,
        tipologia_scavo=fiche.tipologia_scavo,
        stratigrafia=fiche.stratigrafia,
        materiale=fiche.materiale,
        profondita_totale=fiche.profondita_totale,
        diametro_palo=fiche.diametro_palo,
        larghezza_pannello=fiche.larghezza_pannello,
        altezza_pannello=fiche.altezza_pannello,
        site_name=fiche.site.name if fiche.site else "",
        machine_name=fiche.machine.name if fiche.machine else None,
        created_by_name=fiche.created_by.full_name or fiche.created_by.email,
        created_by_role=fiche.created_by.role.value,
    )


@router.post("/", response_model=FicheRead)
def create_fiche(
    fiche_in: FicheCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    site = db.query(Site).filter(Site.id == fiche_in.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    machine = None
    if fiche_in.machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == fiche_in.machine_id).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Macchinario non trovato")

    fiche = Fiche(
        date=fiche_in.date,
        site_id=fiche_in.site_id,
        machine_id=fiche_in.machine_id,
        fiche_type=fiche_in.fiche_type,
        description=fiche_in.description,
        operator=fiche_in.operator,
        hours=fiche_in.hours,
        notes=fiche_in.notes,
        tipologia_scavo=fiche_in.tipologia_scavo,
        stratigrafia=fiche_in.stratigrafia,
        materiale=fiche_in.materiale,
        profondita_totale=fiche_in.profondita_totale,
        diametro_palo=fiche_in.diametro_palo,
        larghezza_pannello=fiche_in.larghezza_pannello,
        altezza_pannello=fiche_in.altezza_pannello,
        created_by_id=current_user.id,
    )
    db.add(fiche)
    db.commit()
    db.refresh(fiche)

    return FicheRead(
        id=fiche.id,
        date=fiche.date,
        site_id=fiche.site_id,
        machine_id=fiche.machine_id,
        fiche_type=fiche.fiche_type,
        description=fiche.description,
        operator=fiche.operator,
        hours=fiche.hours,
        notes=fiche.notes,
        tipologia_scavo=fiche.tipologia_scavo,
        stratigrafia=fiche.stratigrafia,
        materiale=fiche.materiale,
        profondita_totale=fiche.profondita_totale,
        diametro_palo=fiche.diametro_palo,
        larghezza_pannello=fiche.larghezza_pannello,
        altezza_pannello=fiche.altezza_pannello,
        site_name=site.name,
        machine_name=machine.name if machine else None,
        created_by_name=current_user.full_name or current_user.email,
        created_by_role=current_user.role.value,
    )
