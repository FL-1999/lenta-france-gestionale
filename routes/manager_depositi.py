import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import Depot, User
from permissions import has_perm
from template_context import register_manager_badges, render_template

router = APIRouter(tags=["manager-depositi"])
templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
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


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Nome deposito obbligatorio")
    return cleaned


@router.get("/manager/depositi", response_class=HTMLResponse, name="manager_depositi_list")
def manager_depositi_list(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    page, per_page = _normalize_pagination(page, per_page)

    total_count = db.query(func.count(Depot.id)).scalar() or 0
    depositi = (
        db.query(Depot)
        .order_by(Depot.is_active.desc(), Depot.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return render_template(
        templates,
        request,
        "manager/depositi/list.html",
        {
            "depositi": depositi,
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
    _ensure_manager(current_user)
    return render_template(
        templates,
        request,
        "manager/depositi/form.html",
        {
            "depot": None,
            "form_action": request.url_for("manager_depositi_create"),
        },
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
    _ensure_manager(current_user)

    depot_name = _validate_name(name)

    depot = Depot(
        name=depot_name,
        address=_clean_optional(address),
        city=_clean_optional(city),
        zip_code=_clean_optional(zip_code or legacy_zip),
        province=_clean_optional(province),
        country=_clean_optional(country),
        notes=_clean_optional(note),
        lat=_parse_float(lat),
        lng=_parse_float(lng),
        is_active=is_active == "on",
    )
    db.add(depot)
    db.commit()

    return RedirectResponse(url=request.url_for("manager_depositi_list"), status_code=303)


@router.get("/manager/depositi/{depot_id}", response_class=HTMLResponse, name="manager_depositi_edit")
def manager_depositi_edit(
    depot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Deposito non trovato")

    return render_template(
        templates,
        request,
        "manager/depositi/form.html",
        {
            "depot": depot,
            "form_action": request.url_for("manager_depositi_update", depot_id=depot.id),
        },
        db,
        current_user,
    )


@router.post("/manager/depositi/{depot_id}", response_class=HTMLResponse, name="manager_depositi_update")
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
    _ensure_manager(current_user)
    depot = db.query(Depot).filter(Depot.id == depot_id).first()
    if not depot:
        raise HTTPException(status_code=404, detail="Deposito non trovato")

    depot.name = _validate_name(name)
    depot.address = _clean_optional(address)
    depot.city = _clean_optional(city)
    depot.zip_code = _clean_optional(zip_code or legacy_zip)
    depot.province = _clean_optional(province)
    depot.country = _clean_optional(country)
    depot.notes = _clean_optional(note)
    depot.lat = _parse_float(lat)
    depot.lng = _parse_float(lng)
    depot.is_active = is_active == "on"

    db.add(depot)
    db.commit()

    return RedirectResponse(url=request.url_for("manager_depositi_list"), status_code=303)
