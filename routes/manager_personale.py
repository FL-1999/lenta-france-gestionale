from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import get_current_active_user_html
from database import get_session
from models import Personale, User
from template_context import register_manager_badges, render_template
from permissions import has_perm


templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["manager-personale"])


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


@router.get(
    "/manager/personale",
    response_class=HTMLResponse,
    name="manager_personale_list",
)
def manager_personale_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    lang = request.cookies.get("lang", "it")
    personale = session.exec(
        select(Personale).order_by(Personale.cognome, Personale.nome)
    ).all()

    return render_template(
        templates,
        request,
        "manager/personale/personale_list.html",
        {
            "lang": lang,
            "personale": personale,
        },
        session,
        current_user,
    )


@router.get(
    "/manager/personale/new",
    response_class=HTMLResponse,
    name="manager_personale_new",
)
def manager_personale_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    lang = request.cookies.get("lang", "it")
    return render_template(
        templates,
        request,
        "manager/personale/personale_new.html",
        {
            "lang": lang,
        },
        None,
        current_user,
    )


@router.post(
    "/manager/personale/new",
    response_class=HTMLResponse,
    name="manager_personale_create",
)
def manager_personale_create(
    request: Request,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    data_assunzione: Optional[date] = Form(None),
    attivo: bool = Form(False),
    note: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale = Personale(
        nome=nome.strip(),
        cognome=cognome.strip(),
        ruolo=(ruolo or "").strip() or None,
        telefono=(telefono or "").strip() or None,
        email=(email or "").strip() or None,
        data_assunzione=data_assunzione,
        attivo=attivo,
        note=(note or "").strip() or None,
    )
    session.add(personale)
    session.commit()

    url = request.url_for("manager_personale_list")
    return RedirectResponse(url=url, status_code=303)


@router.get(
    "/manager/personale/{personale_id}/edit",
    response_class=HTMLResponse,
    name="manager_personale_edit",
)
def manager_personale_edit(
    request: Request,
    personale_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    lang = request.cookies.get("lang", "it")
    personale = session.get(Personale, personale_id)
    if not personale:
        return RedirectResponse(
            request.url_for("manager_personale_list"), status_code=303
        )

    return render_template(
        templates,
        request,
        "manager/personale/personale_edit.html",
        {
            "lang": lang,
            "personale": personale,
        },
        session,
        current_user,
    )


@router.post(
    "/manager/personale/{personale_id}/edit",
    response_class=HTMLResponse,
    name="manager_personale_update",
)
def manager_personale_update(
    request: Request,
    personale_id: int,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    data_assunzione: Optional[date] = Form(None),
    attivo: bool = Form(False),
    note: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    personale = session.get(Personale, personale_id)
    if not personale:
        return RedirectResponse(
            request.url_for("manager_personale_list"), status_code=303
        )

    personale.nome = nome.strip()
    personale.cognome = cognome.strip()
    personale.ruolo = (ruolo or "").strip() or None
    personale.telefono = (telefono or "").strip() or None
    personale.email = (email or "").strip() or None
    personale.data_assunzione = data_assunzione
    personale.attivo = attivo
    personale.note = (note or "").strip() or None

    session.add(personale)
    session.commit()

    url = request.url_for("manager_personale_list")
    return RedirectResponse(url=url, status_code=303)


@router.post(
    "/manager/personale/{personale_id}/delete",
    response_class=HTMLResponse,
    name="manager_personale_delete",
)
def manager_personale_delete(
    request: Request,
    personale_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    if not has_perm(current_user, "records.delete"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")

    personale = session.get(Personale, personale_id)
    if personale:
        session.delete(personale)
        session.commit()

    return RedirectResponse(
        url=request.url_for("manager_personale_list"), status_code=303
    )
