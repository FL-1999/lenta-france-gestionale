import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import Attrezzatura, Depot, Machine, MachineSiteAssignment, MagazzinoMovimento, User
from permissions import can_access_depots, can_manage_depots
from template_context import register_manager_badges, render_template

router = APIRouter(tags=["manager-depositi"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100


def _real_depots_query(db: Session):
    return db.query(Depot)


def _format_depot_label(depot: Depot) -> str:
    return f"[Deposito] {depot.name}"


def _depot_address(depot: Depot) -> str:
    parts = [depot.address, depot.city, depot.zip_code, depot.province, depot.country]
    return ", ".join(str(part).strip() for part in parts if part and str(part).strip()) or "—"


def _ensure_depots_read(user: User) -> None:
    if not can_access_depots(user):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_depots_manage(user: User) -> None:
    if not can_manage_depots(user):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_coordinate(value: str | None, field_label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_label} non valida") from exc


def _validate_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Nome deposito obbligatorio")
    return cleaned


def _find_depot_by_name(db: Session, name: str, *, exclude_id: int | None = None) -> Depot | None:
    with db.no_autoflush:
        query = db.query(Depot).filter(func.lower(func.trim(Depot.name)) == name.strip().lower())
        if exclude_id is not None:
            query = query.filter(Depot.id != exclude_id)
        return query.first()


def _build_form_context(request: Request, *, depot: Depot | None, form_action: str, form_data: dict | None = None, error_message: str | None = None) -> dict:
    return {
        "depot": depot,
        "form_action": form_action,
        "form_data": form_data or {},
        "error_message": error_message,
    }


def _extract_depot_form_payload(
    name: str,
    address: str | None,
    city: str | None,
    zip_code: str | None,
    legacy_zip: str | None,
    province: str | None,
    country: str | None,
    note: str | None,
    lat: str | None,
    lng: str | None,
    is_active: str | None,
) -> dict:
    return {
        "name": name,
        "address": address or "",
        "city": city or "",
        "zip_code": zip_code or legacy_zip or "",
        "province": province or "",
        "country": country or "",
        "note": note or "",
        "lat": lat or "",
        "lng": lng or "",
        "is_active": bool(is_active == "on"),
    }


def _apply_depot_payload(depot: Depot, payload: dict) -> None:
    depot.name = _validate_name(payload.get("name"))
    depot.address = _clean_optional(payload.get("address"))
    depot.city = _clean_optional(payload.get("city"))
    depot.zip_code = _clean_optional(payload.get("zip_code"))
    depot.province = _clean_optional(payload.get("province"))
    depot.country = _clean_optional(payload.get("country"))
    depot.notes = _clean_optional(payload.get("note"))
    depot.lat = _parse_coordinate(payload.get("lat"), "Latitudine")
    depot.lng = _parse_coordinate(payload.get("lng"), "Longitudine")
    depot.is_active = bool(payload.get("is_active"))


@router.get("/manager/depositi", response_class=HTMLResponse, name="manager_depositi_list")
def manager_depositi_list(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_read(current_user)
    page, per_page = _normalize_pagination(page, per_page)

    total_count = _real_depots_query(db).with_entities(func.count(Depot.id)).scalar() or 0
    depots = (
        _real_depots_query(db)
        .order_by(Depot.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    print("depots count:", total_count)
    print("nomi depositi trovati:", [depot.name for depot in depots])

    return render_template(
        templates,
        request,
        "manager/depositi/list.html",
        {
            "depots": depots,
            "depositi": depots,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, math.ceil(total_count / per_page)),
        },
        db,
        current_user,
    )


@router.get("/manager/depositi/nuovo", response_class=HTMLResponse, name="manager_depositi_new")
def manager_depositi_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_manage(current_user)
    return render_template(
        templates,
        request,
        "manager/depositi/form.html",
        _build_form_context(
            request,
            depot=None,
            form_action=str(request.url_for("manager_depositi_create")),
        ),
        db,
        current_user,
    )


@router.post("/manager/depositi/nuovo", response_class=HTMLResponse, name="manager_depositi_create")
def manager_depositi_create(
    request: Request,
    name: str = Form(...),
    address: str | None = Form(None),
    city: str | None = Form(None),
    zip_code: str | None = Form(None),
    legacy_zip: str | None = Form(None, alias="zip"),
    province: str | None = Form(None),
    country: str | None = Form(None),
    note: str | None = Form(None),
    lat: str | None = Form(None),
    lng: str | None = Form(None),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_manage(current_user)

    payload = _extract_depot_form_payload(name, address, city, zip_code, legacy_zip, province, country, note, lat, lng, is_active)
    payload["is_active"] = True
    print("creating depot:", payload.get("name"))
    depot = Depot()
    try:
        _apply_depot_payload(depot, payload)
    except HTTPException as exc:
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=None,
                form_action=str(request.url_for("manager_depositi_create")),
                form_data=payload,
                error_message=exc.detail,
            ),
            db,
            current_user,
            status_code=exc.status_code,
        )

    if _find_depot_by_name(db, depot.name):
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=None,
                form_action=str(request.url_for("manager_depositi_create")),
                form_data=payload,
                error_message="Deposito già esistente",
            ),
            db,
            current_user,
            status_code=400,
        )

    db.add(depot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=None,
                form_action=str(request.url_for("manager_depositi_create")),
                form_data=payload,
                error_message="Deposito già esistente",
            ),
            db,
            current_user,
            status_code=400,
        )

    return RedirectResponse(url=request.url_for("manager_depositi_list"), status_code=303)


@router.get("/manager/depositi/{depot_id}", response_class=HTMLResponse, name="manager_depositi_detail")
def manager_depositi_detail(
    depot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_read(current_user)
    depot = _real_depots_query(db).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Deposito non trovato")

    depot_label = _format_depot_label(depot)
    machine_assignments = (
        db.query(MachineSiteAssignment)
        .options(joinedload(MachineSiteAssignment.machine))
        .join(Machine, Machine.id == MachineSiteAssignment.machine_id)
        .filter(MachineSiteAssignment.unassigned_at.is_(None))
        .filter(MachineSiteAssignment.location_label == depot_label)
        .order_by(Machine.name.asc())
        .all()
    )
    attrezzature = (
        db.query(Attrezzatura)
        .filter(func.lower(func.trim(Attrezzatura.posizione_attuale)) == depot.name.strip().lower())
        .order_by(Attrezzatura.nome.asc())
        .all()
    )
    materiali = (
        db.query(
            MagazzinoMovimento.item_id,
            func.sum(MagazzinoMovimento.quantita).label("quantita"),
        )
        .filter(MagazzinoMovimento.deposito_id == depot.id)
        .group_by(MagazzinoMovimento.item_id)
        .all()
    )
    material_rows = []
    for row in materiali:
        movimento = (
            db.query(MagazzinoMovimento)
            .options(joinedload(MagazzinoMovimento.item))
            .filter(
                MagazzinoMovimento.deposito_id == depot.id,
                MagazzinoMovimento.item_id == row.item_id,
            )
            .order_by(MagazzinoMovimento.created_at.desc())
            .first()
        )
        if movimento and movimento.item:
            material_rows.append({"item": movimento.item, "quantita": row.quantita})

    return render_template(
        templates,
        request,
        "manager/depositi/detail.html",
        {
            "depot": depot,
            "depot_address": _depot_address(depot),
            "machine_assignments": machine_assignments,
            "attrezzature": attrezzature,
            "material_rows": material_rows,
        },
        db,
        current_user,
    )


@router.get("/manager/depositi/{depot_id}/modifica", response_class=HTMLResponse, name="manager_depositi_edit")
def manager_depositi_edit(
    depot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_manage(current_user)
    depot = _real_depots_query(db).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Deposito non trovato")

    return render_template(
        templates,
        request,
        "manager/depositi/form.html",
        _build_form_context(
            request,
            depot=depot,
            form_action=str(request.url_for("manager_depositi_update", depot_id=depot.id)),
        ),
        db,
        current_user,
    )


@router.post("/manager/depositi/{depot_id}/modifica", response_class=HTMLResponse, name="manager_depositi_update")
@router.post("/manager/depositi/{depot_id}", response_class=HTMLResponse)
def manager_depositi_update(
    depot_id: int,
    request: Request,
    name: str = Form(...),
    address: str | None = Form(None),
    city: str | None = Form(None),
    zip_code: str | None = Form(None),
    legacy_zip: str | None = Form(None, alias="zip"),
    province: str | None = Form(None),
    country: str | None = Form(None),
    note: str | None = Form(None),
    lat: str | None = Form(None),
    lng: str | None = Form(None),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_depots_manage(current_user)
    depot = _real_depots_query(db).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Deposito non trovato")

    payload = _extract_depot_form_payload(name, address, city, zip_code, legacy_zip, province, country, note, lat, lng, is_active)
    try:
        _apply_depot_payload(depot, payload)
    except HTTPException as exc:
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=depot,
                form_action=str(request.url_for("manager_depositi_update", depot_id=depot.id)),
                form_data=payload,
                error_message=exc.detail,
            ),
            db,
            current_user,
            status_code=exc.status_code,
        )

    if _find_depot_by_name(db, depot.name, exclude_id=depot.id):
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=depot,
                form_action=str(request.url_for("manager_depositi_update", depot_id=depot.id)),
                form_data=payload,
                error_message="Deposito già esistente",
            ),
            db,
            current_user,
            status_code=400,
        )

    db.add(depot)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/depositi/form.html",
            _build_form_context(
                request,
                depot=depot,
                form_action=str(request.url_for("manager_depositi_update", depot_id=depot.id)),
                form_data=payload,
                error_message="Deposito già esistente",
            ),
            db,
            current_user,
            status_code=400,
        )

    return RedirectResponse(url=request.url_for("manager_depositi_list"), status_code=303)
