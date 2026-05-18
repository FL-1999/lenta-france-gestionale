import logging
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user
from database import get_db
from deps import get_site_for_user
from models import Fiche, FicheTypeEnum, RoleEnum, Site, Machine, User
from schemas import FicheCreate, FicheRead, FicheListItem
from notifications import notify_new_fiche

router = APIRouter(prefix="/fiches", tags=["fiches"])
logger = logging.getLogger("lenta_france_gestionale.errors")


def _sorted_courbe_points(points):
    if not points:
        return []
    normalized = []
    for point in points:
        try:
            volume = float(point.get("volume"))
            hauteur = float(point.get("hauteur"))
        except (AttributeError, TypeError, ValueError):
            continue
        normalized.append({"volume": volume, "hauteur": hauteur})
    return sorted(normalized, key=lambda point: point["volume"])


def _json_courbe_points(points) -> str | None:
    normalized = _sorted_courbe_points(points)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) if normalized else None


def _load_courbe_points(raw: str | None):
    if not raw:
        return []
    try:
        return _sorted_courbe_points(json.loads(raw))
    except (TypeError, ValueError):
        return []


def _sync_site_fiche_progress(db: Session, site: Site) -> None:
    paratie_scavate = (
        db.query(func.count(Fiche.id))
        .filter(Fiche.site_id == site.id, func.lower(Fiche.tipologia_scavo) == "paratia")
        .scalar()
        or 0
    )
    site.paratie_done_panels = int(paratie_scavate)
    if site.totale_paratie_da_scavare is not None:
        site.paratie_total_panels = site.totale_paratie_da_scavare
    paratie_total = int(
        site.totale_paratie_da_scavare
        if site.totale_paratie_da_scavare is not None
        else (site.paratie_total_panels or 0)
    )
    site.progress = (
        int(round((int(paratie_scavate) / paratie_total) * 100))
        if paratie_total > 0
        else 0
    )


def _normalize_fiche_tipologia(tipologia_scavo: str | None) -> str:
    tipologia = (tipologia_scavo or "").strip().lower()
    if tipologia not in {"paratia", "palo"}:
        raise HTTPException(
            status_code=400,
            detail="Selezionare una tipologia di scavo valida: paratia o palo.",
        )
    return tipologia


def _ensure_unique_numero_pannello(
    db: Session, site_id: int, tipologia_scavo: str | None, numero_pannello: int
) -> None:
    normalized_tipologia = _normalize_fiche_tipologia(tipologia_scavo)
    duplicate_exists = (
        db.query(Fiche.id)
        .filter(
            Fiche.site_id == site_id,
            func.lower(Fiche.tipologia_scavo) == normalized_tipologia,
            Fiche.numero_pannello == numero_pannello,
        )
        .first()
        is not None
    )
    if duplicate_exists:
        label = "Paratia" if normalized_tipologia == "paratia" else "Palo"
        raise HTTPException(
            status_code=400,
            detail=f"{label} {numero_pannello} già registrato per questo cantiere",
        )



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
    if current_user.role == RoleEnum.caposquadra:
        query = query.filter(Site.caposquadra_id == current_user.id)
    if site_id:
        if current_user.role == RoleEnum.caposquadra:
            get_site_for_user(db, site_id, current_user)
        query = query.filter(Fiche.site_id == site_id)
    if fiche_type:
        query = query.filter(Fiche.fiche_type == fiche_type)

    fiches = query.order_by(Fiche.date.desc(), Fiche.id.desc()).all()

    return [
        FicheListItem(
            id=fiche.id,
            date=fiche.date,
            site_name=fiche.site.name if fiche.site else "",
            numero_pannello=fiche.numero_pannello,
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
            data_getto=fiche.data_getto,
            metri_cubi_gettati=fiche.metri_cubi_gettati,
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
            joinedload(Fiche.capocantiere),
        )
        .filter(Fiche.id == fiche_id)
        .first()
    )

    if not fiche:
        raise HTTPException(status_code=404, detail="Fiche non trovata")
    if current_user.role == RoleEnum.caposquadra:
        get_site_for_user(db, fiche.site_id, current_user)

    return FicheRead(
        id=fiche.id,
        date=fiche.date,
        site_id=fiche.site_id,
        numero_pannello=fiche.numero_pannello,
        machine_id=fiche.machine_id,
        capocantiere_id=fiche.capocantiere_id,
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
        data_getto=fiche.data_getto,
        metri_cubi_gettati=fiche.metri_cubi_gettati,
        quota_ngf_testa=fiche.quota_ngf_testa,
        quota_ngf_fondo=fiche.quota_ngf_fondo,
        quota_ngf_note=fiche.quota_ngf_note,
        courbe_beton_active=fiche.courbe_beton_active,
        courbe_beton_realisee=_load_courbe_points(fiche.courbe_beton_realisee),
        courbe_beton_tube=_load_courbe_points(fiche.courbe_beton_tube),
        courbe_beton_volume_total=fiche.courbe_beton_volume_total,
        courbe_beton_hauteur_initiale=fiche.courbe_beton_hauteur_initiale,
        courbe_beton_hauteur_finale=fiche.courbe_beton_hauteur_finale,
        site_name=fiche.site.name if fiche.site else "",
        machine_name=fiche.machine.name if fiche.machine else None,
        capocantiere_name=(fiche.capocantiere.full_name or fiche.capocantiere.email) if fiche.capocantiere else None,
        created_by_name=fiche.created_by.full_name or fiche.created_by.email,
        created_by_role=fiche.created_by.role.value,
    )


@router.post("/", response_model=FicheRead)
def create_fiche(
    fiche_in: FicheCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    site = get_site_for_user(db, fiche_in.site_id, current_user)
    normalized_tipologia = _normalize_fiche_tipologia(fiche_in.tipologia_scavo)
    _ensure_unique_numero_pannello(
        db, fiche_in.site_id, normalized_tipologia, fiche_in.numero_pannello
    )

    machine = None
    if fiche_in.machine_id is not None:
        machine = db.query(Machine).filter(Machine.id == fiche_in.machine_id).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Macchinario non trovato")

    fiche = Fiche(
        date=fiche_in.date,
        numero_pannello=fiche_in.numero_pannello,
        site_id=fiche_in.site_id,
        machine_id=fiche_in.machine_id,
        capocantiere_id=fiche_in.capocantiere_id if current_user.role in {RoleEnum.admin, RoleEnum.manager} else None,
        fiche_type=fiche_in.fiche_type,
        description=fiche_in.description,
        operator=fiche_in.operator,
        hours=fiche_in.hours,
        notes=fiche_in.notes,
        tipologia_scavo=normalized_tipologia,
        materiale=fiche_in.materiale,
        profondita_totale=fiche_in.profondita_totale,
        diametro_palo=fiche_in.diametro_palo,
        larghezza_pannello=fiche_in.larghezza_pannello,
        altezza_pannello=fiche_in.altezza_pannello,
        data_getto=fiche_in.data_getto,
        metri_cubi_gettati=fiche_in.metri_cubi_gettati,
        courbe_beton_active=bool(fiche_in.courbe_beton_active) if current_user.role in {RoleEnum.admin, RoleEnum.manager} else False,
        courbe_beton_realisee=_json_courbe_points(fiche_in.courbe_beton_realisee) if current_user.role in {RoleEnum.admin, RoleEnum.manager} and fiche_in.courbe_beton_active else None,
        courbe_beton_tube=_json_courbe_points(fiche_in.courbe_beton_tube) if current_user.role in {RoleEnum.admin, RoleEnum.manager} and fiche_in.courbe_beton_active else None,
        courbe_beton_volume_total=fiche_in.courbe_beton_volume_total if current_user.role in {RoleEnum.admin, RoleEnum.manager} and fiche_in.courbe_beton_active else None,
        courbe_beton_hauteur_initiale=fiche_in.courbe_beton_hauteur_initiale if current_user.role in {RoleEnum.admin, RoleEnum.manager} and fiche_in.courbe_beton_active else None,
        courbe_beton_hauteur_finale=fiche_in.courbe_beton_hauteur_finale if current_user.role in {RoleEnum.admin, RoleEnum.manager} and fiche_in.courbe_beton_active else None,
        created_by_id=current_user.id,
    )
    db.add(fiche)
    db.flush()
    _sync_site_fiche_progress(db, site)
    fiche_notifications = notify_new_fiche(db, fiche, current_user)
    logger.info(
        "notification created for fiche id %s: %s recipient(s)",
        fiche.id,
        len(fiche_notifications),
    )
    db.commit()
    db.refresh(fiche)

    return FicheRead(
        id=fiche.id,
        date=fiche.date,
        site_id=fiche.site_id,
        numero_pannello=fiche.numero_pannello,
        machine_id=fiche.machine_id,
        capocantiere_id=fiche.capocantiere_id,
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
        data_getto=fiche.data_getto,
        metri_cubi_gettati=fiche.metri_cubi_gettati,
        quota_ngf_testa=fiche.quota_ngf_testa,
        quota_ngf_fondo=fiche.quota_ngf_fondo,
        quota_ngf_note=fiche.quota_ngf_note,
        courbe_beton_active=fiche.courbe_beton_active,
        courbe_beton_realisee=_load_courbe_points(fiche.courbe_beton_realisee),
        courbe_beton_tube=_load_courbe_points(fiche.courbe_beton_tube),
        courbe_beton_volume_total=fiche.courbe_beton_volume_total,
        courbe_beton_hauteur_initiale=fiche.courbe_beton_hauteur_initiale,
        courbe_beton_hauteur_finale=fiche.courbe_beton_hauteur_finale,
        site_name=site.name,
        machine_name=machine.name if machine else None,
        capocantiere_name=None,
        created_by_name=current_user.full_name or current_user.email,
        created_by_role=current_user.role.value,
    )
