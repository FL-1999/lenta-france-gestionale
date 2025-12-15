from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import RoleEnum, User
from models.veicoli import Veicolo


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["manager-veicoli"])


def _ensure_manager(user: User) -> None:
    if user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


@router.get(
    "/manager/veicoli",
    response_class=HTMLResponse,
    name="manager_veicoli_list",
)
def manager_veicoli_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    veicoli = db.query(Veicolo).order_by(Veicolo.marca.asc(), Veicolo.modello.asc()).all()
    return templates.TemplateResponse(
        "manager/veicoli/veicoli_list.html",
        {
            "request": request,
            "user": current_user,
            "veicoli": veicoli,
        },
    )


@router.get(
    "/manager/veicoli/nuovo",
    response_class=HTMLResponse,
    name="manager_veicoli_new",
)
def manager_veicoli_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    return templates.TemplateResponse(
        "manager/veicoli/veicoli_new.html",
        {"request": request, "user": current_user},
    )


@router.post(
    "/manager/veicoli/nuovo",
    response_class=HTMLResponse,
    name="manager_veicoli_create",
)
def manager_veicoli_create(
    request: Request,
    marca: str = Form(...),
    modello: str = Form(...),
    targa: str = Form(...),
    anno: str | None = Form(None),
    km: str | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    veicolo = Veicolo(
        marca=marca.strip(),
        modello=modello.strip(),
        targa=targa.strip().upper(),
        anno=_parse_int(anno),
        km=_parse_int(km),
        note=(note or "").strip() or None,
    )
    db.add(veicolo)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_veicoli_list"), status_code=303
    )


@router.get(
    "/manager/veicoli/{veicolo_id}/modifica",
    response_class=HTMLResponse,
    name="manager_veicoli_edit",
)
def manager_veicoli_edit(
    veicolo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    veicolo = db.query(Veicolo).filter(Veicolo.id == veicolo_id).first()
    if not veicolo:
        return RedirectResponse(
            url=request.url_for("manager_veicoli_list"), status_code=303
        )

    return templates.TemplateResponse(
        "manager/veicoli/veicoli_edit.html",
        {
            "request": request,
            "user": current_user,
            "veicolo": veicolo,
        },
    )


@router.post(
    "/manager/veicoli/{veicolo_id}/modifica",
    response_class=HTMLResponse,
    name="manager_veicoli_update",
)
def manager_veicoli_update(
    veicolo_id: int,
    request: Request,
    marca: str = Form(...),
    modello: str = Form(...),
    targa: str = Form(...),
    anno: str | None = Form(None),
    km: str | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    veicolo = db.query(Veicolo).filter(Veicolo.id == veicolo_id).first()
    if not veicolo:
        return RedirectResponse(
            url=request.url_for("manager_veicoli_list"), status_code=303
        )

    veicolo.marca = marca.strip()
    veicolo.modello = modello.strip()
    veicolo.targa = targa.strip().upper()
    veicolo.anno = _parse_int(anno)
    veicolo.km = _parse_int(km)
    veicolo.note = (note or "").strip() or None

    db.add(veicolo)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_veicoli_list"), status_code=303
    )


@router.post(
    "/manager/veicoli/{veicolo_id}/elimina",
    response_class=HTMLResponse,
    name="manager_veicoli_delete",
)
def manager_veicoli_delete(
    veicolo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    veicolo = db.query(Veicolo).filter(Veicolo.id == veicolo_id).first()
    if veicolo:
        db.delete(veicolo)
        db.commit()

    return RedirectResponse(
        url=request.url_for("manager_veicoli_list"), status_code=303
    )
