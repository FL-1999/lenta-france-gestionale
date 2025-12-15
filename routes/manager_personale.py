from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import get_session
from models import Personale


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["manager-personale"])


@router.get("/manager/personale", response_class=HTMLResponse)
async def manager_personale_list(
    request: Request,
    session: Session = Depends(get_session),
):
    lang = request.cookies.get("lang", "it")
    personale = session.exec(
        select(Personale).order_by(Personale.cognome, Personale.nome)
    ).all()

    return templates.TemplateResponse(
        "manager/personale_list.html",
        {"request": request, "lang": lang, "personale": personale},
    )


@router.get("/manager/personale/nuovo", response_class=HTMLResponse)
async def manager_personale_new(
    request: Request,
):
    lang = request.cookies.get("lang", "it")
    return templates.TemplateResponse(
        "manager/personale_form.html",
        {
            "request": request,
            "lang": lang,
            "personale": None,
        },
    )


@router.post("/manager/personale/nuovo", response_class=HTMLResponse)
async def manager_personale_create(
    request: Request,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    data_assunzione: Optional[date] = Form(None),
    attivo: bool = Form(True),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    personale = Personale(
        nome=nome.strip(),
        cognome=cognome.strip(),
        ruolo=ruolo or None,
        telefono=telefono or None,
        email=email or None,
        data_assunzione=data_assunzione,
        attivo=attivo,
        note=note or None,
    )
    session.add(personale)
    session.commit()

    url = request.url_for("manager_personale_list")
    return RedirectResponse(url=url, status_code=303)


@router.get("/manager/personale/{personale_id}/modifica", response_class=HTMLResponse)
async def manager_personale_edit(
    request: Request,
    personale_id: int,
    session: Session = Depends(get_session),
):
    lang = request.cookies.get("lang", "it")
    personale = session.get(Personale, personale_id)
    if not personale:
        return RedirectResponse(request.url_for("manager_personale_list"), status_code=303)

    return templates.TemplateResponse(
        "manager/personale_form.html",
        {
            "request": request,
            "lang": lang,
            "personale": personale,
        },
    )


@router.post("/manager/personale/{personale_id}/modifica", response_class=HTMLResponse)
async def manager_personale_update(
    request: Request,
    personale_id: int,
    nome: str = Form(...),
    cognome: str = Form(...),
    ruolo: str = Form(""),
    telefono: str = Form(""),
    email: str = Form(""),
    data_assunzione: Optional[date] = Form(None),
    attivo: bool = Form(True),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    personale = session.get(Personale, personale_id)
    if not personale:
        return RedirectResponse(request.url_for("manager_personale_list"), status_code=303)

    personale.nome = nome.strip()
    personale.cognome = cognome.strip()
    personale.ruolo = ruolo or None
    personale.telefono = telefono or None
    personale.email = email or None
    personale.data_assunzione = data_assunzione
    personale.attivo = attivo
    personale.note = note or None

    session.add(personale)
    session.commit()

    url = request.url_for("manager_personale_list")
    return RedirectResponse(url=url, status_code=303)
