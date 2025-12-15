from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import User, RoleEnum
from models.personale import Personale


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["manager-personale"])


def _ensure_manager(user: User) -> None:
    if user.role not in (RoleEnum.admin, RoleEnum.manager):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


@router.get(
    "/manager/personale",
    response_class=HTMLResponse,
    name="manager_personale_list",
)
def manager_personale_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale_list = (
        db.query(Personale)
        .order_by(Personale.cognome.asc(), Personale.nome.asc())
        .all()
    )
    return templates.TemplateResponse(
        "manager/personale/personale_list.html",
        {
            "request": request,
            "user": current_user,
            "personale": personale_list,
        },
    )


@router.get(
    "/manager/personale/nuovo",
    response_class=HTMLResponse,
    name="manager_personale_new",
)
def manager_personale_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    return templates.TemplateResponse(
        "manager/personale/personale_new.html",
        {"request": request, "user": current_user},
    )


@router.post(
    "/manager/personale/nuovo",
    response_class=HTMLResponse,
    name="manager_personale_create",
)
def manager_personale_create(
    request: Request,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str | None = Form(None),
    telefono: str | None = Form(None),
    email: str | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    nuovo_personale = Personale(
        nome=nome.strip(),
        cognome=cognome.strip(),
        ruolo=(ruolo or "").strip() or None,
        telefono=(telefono or "").strip() or None,
        email=(email or "").strip() or None,
        note=(note or "").strip() or None,
    )
    db.add(nuovo_personale)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_personale_list"), status_code=303
    )


@router.get(
    "/manager/personale/{personale_id}/modifica",
    response_class=HTMLResponse,
    name="manager_personale_edit",
)
def manager_personale_edit(
    personale_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale_obj = (
        db.query(Personale)
        .filter(Personale.id == personale_id)
        .first()
    )
    if not personale_obj:
        return RedirectResponse(
            url=request.url_for("manager_personale_list"), status_code=303
        )

    return templates.TemplateResponse(
        "manager/personale/personale_edit.html",
        {
            "request": request,
            "user": current_user,
            "personale": personale_obj,
        },
    )


@router.post(
    "/manager/personale/{personale_id}/modifica",
    response_class=HTMLResponse,
    name="manager_personale_update",
)
def manager_personale_update(
    personale_id: int,
    request: Request,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str | None = Form(None),
    telefono: str | None = Form(None),
    email: str | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale_obj = (
        db.query(Personale)
        .filter(Personale.id == personale_id)
        .first()
    )
    if not personale_obj:
        return RedirectResponse(
            url=request.url_for("manager_personale_list"), status_code=303
        )

    personale_obj.nome = nome.strip()
    personale_obj.cognome = cognome.strip()
    personale_obj.ruolo = (ruolo or "").strip() or None
    personale_obj.telefono = (telefono or "").strip() or None
    personale_obj.email = (email or "").strip() or None
    personale_obj.note = (note or "").strip() or None

    db.add(personale_obj)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_personale_list"), status_code=303
    )


@router.post(
    "/manager/personale/{personale_id}/elimina",
    response_class=HTMLResponse,
    name="manager_personale_delete",
)
def manager_personale_delete(
    personale_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale_obj = (
        db.query(Personale)
        .filter(Personale.id == personale_id)
        .first()
    )
    if personale_obj:
        db.delete(personale_obj)
        db.commit()

    return RedirectResponse(
        url=request.url_for("manager_personale_list"), status_code=303
    )
