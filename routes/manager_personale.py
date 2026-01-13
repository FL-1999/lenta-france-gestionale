import calendar
import logging
import time
from typing import Optional
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sqlalchemy import func

from auth import get_current_active_user_html
from database import get_session
from models import Personale, PersonalePresenza, Site, User
from personale_presenze_repository import (
    copy_week_attendance_from_monday,
    get_week_attendance,
    upsert_personale_presenza,
)
from template_context import register_manager_badges, render_template
from permissions import has_perm


templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["manager-personale"])
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100

perf_logger = logging.getLogger("lenta_france_gestionale.performance")
ATTENDANCE_STATUSES = [
    ("WORK", "Lavoro"),
    ("FERIE", "Ferie"),
    ("PERMESSO", "Permesso"),
    ("MALATTIA", "Malattia"),
    ("RIPOSO", "Riposo"),
]
ATTENDANCE_STATUS_CLASSES = {
    "WORK": "badge-work",
    "FERIE": "badge-ferie",
    "PERMESSO": "badge-permesso",
    "MALATTIA": "badge-malattia",
    "RIPOSO": "badge-riposo",
}
MONTH_NAMES_IT = [
    "",
    "Gennaio",
    "Febbraio",
    "Marzo",
    "Aprile",
    "Maggio",
    "Giugno",
    "Luglio",
    "Agosto",
    "Settembre",
    "Ottobre",
    "Novembre",
    "Dicembre",
]


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError:
        return None
    return parsed.year, parsed.month


def _get_week_start(value: date | None) -> date:
    if value:
        return value
    today = date.today()
    return today - timedelta(days=today.weekday())


@router.get(
    "/manager/personale",
    response_class=HTMLResponse,
    name="manager_personale_list",
)
def manager_personale_list(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "users.read"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    lang = request.cookies.get("lang", "it")
    page, per_page = _normalize_pagination(page, per_page)
    total_count = session.exec(select(func.count(Personale.id))).one()
    query_started = time.monotonic()
    personale = session.exec(
        select(Personale)
        .order_by(Personale.cognome, Personale.nome)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    perf_logger.debug(
        "manager_personale_list rows=%s total=%s page=%s per_page=%s duration_ms=%.2f",
        len(personale),
        total_count,
        page,
        per_page,
        (time.monotonic() - query_started) * 1000,
    )

    return render_template(
        templates,
        request,
        "manager/personale/personale_list.html",
        {
            "lang": lang,
            "personale": personale,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total_count + per_page - 1) // per_page),
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


@router.get(
    "/manager/personale/presenze",
    response_class=HTMLResponse,
    name="manager_personale_presenze",
)
def manager_personale_presenze(
    request: Request,
    view: str | None = None,
    week_start: Optional[date] = None,
    month: str | None = None,
    personale_id: Optional[int] = None,
    autofill: str | None = None,
    autofill_personale: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    lang = request.cookies.get("lang", "it")
    view = (view or "week").lower()
    if view not in {"week", "month"}:
        view = "week"
    week_start = _get_week_start(week_start)
    week_end = week_start + timedelta(days=6)
    week_days = [week_start + timedelta(days=offset) for offset in range(7)]

    personale_query = (
        select(Personale)
        .where(Personale.attivo.is_(True))
        .order_by(Personale.cognome, Personale.nome)
    )
    personale_list = session.exec(personale_query).all()
    personale = personale_list
    if personale_id and view != "month":
        personale = [worker for worker in personale_list if worker.id == personale_id]
    personale_by_id = {worker.id: worker for worker in personale_list}

    presenze = get_week_attendance(session, week_start, week_end, personale_id)
    sites = session.exec(
        select(Site)
        .where(Site.is_active.is_(True))
        .order_by(Site.code, Site.name)
    ).all()
    site_map = {site.id: site for site in sites if site.id is not None}

    attendance_map: dict[int, dict[date, dict[str, object]]] = {}
    for presenza in presenze:
        site = site_map.get(presenza.site_id)
        attendance_map.setdefault(presenza.personale_id, {})[presenza.attendance_date] = {
            "status": presenza.status,
            "site_id": presenza.site_id,
            "site_code": site.code if site else None,
            "site_name": site.name if site else None,
            "hours": presenza.hours,
            "note": presenza.note,
        }

    parsed_month = _parse_month(month)
    if parsed_month:
        month_year, month_number = parsed_month
    else:
        today = date.today()
        month_year, month_number = today.year, today.month
    selected_month = f"{month_year:04d}-{month_number:02d}"
    month_start = date(month_year, month_number, 1)
    last_day = calendar.monthrange(month_year, month_number)[1]
    month_end = date(month_year, month_number, last_day)
    month_calendar = calendar.Calendar(firstweekday=0)
    month_weeks = [
        [day if day.month == month_number else None for day in week]
        for week in month_calendar.monthdatescalendar(month_year, month_number)
    ]
    month_context = {
        "year": month_year,
        "month": month_number,
        "month_label": f"{MONTH_NAMES_IT[month_number]} {month_year}",
        "weeks": month_weeks,
    }

    selected_personale = personale_by_id.get(personale_id) if personale_id else None
    attendance_by_date: dict[date, dict[str, object]] = {}
    if view == "month" and selected_personale:
        month_presenze = session.exec(
            select(PersonalePresenza).where(
                PersonalePresenza.personale_id == personale_id,
                PersonalePresenza.attendance_date >= month_start,
                PersonalePresenza.attendance_date <= month_end,
            )
        ).all()
        for presenza in month_presenze:
            site = site_map.get(presenza.site_id)
            attendance_by_date[presenza.attendance_date] = {
                "status": presenza.status,
                "site_id": presenza.site_id,
                "site_code": site.code if site else None,
                "site_name": site.name if site else None,
                "hours": presenza.hours,
                "note": presenza.note,
            }

    success_message = None
    error_message = None
    if autofill == "missing":
        error_message = "Nessuna presenza il lunedì da copiare."
    elif autofill == "noop":
        error_message = "Nessuna cella vuota da compilare con il lunedì."
    elif autofill == "success":
        target = personale_by_id.get(autofill_personale)
        if target:
            success_message = (
                "Presenze copiate da lunedì per "
                f"{target.cognome} {target.nome} (mar–dom, solo celle vuote)."
            )
        else:
            success_message = "Presenze copiate da lunedì (mar–dom, solo celle vuote)."

    # TODO: aggiungere export CSV settimanale per manager.

    return render_template(
        templates,
        request,
        "manager/personale/personale_presenze.html",
        {
            "lang": lang,
            "view": view,
            "personale": personale,
            "personale_list": personale_list,
            "selected_personale": selected_personale,
            "week_start": week_start,
            "week_end": week_end,
            "week_days": week_days,
            "prev_week": week_start - timedelta(days=7),
            "next_week": week_start + timedelta(days=7),
            "attendance_map": attendance_map,
            "attendance_by_date": attendance_by_date,
            "month_context": month_context,
            "selected_month": selected_month,
            "sites": sites,
            "status_options": ATTENDANCE_STATUSES,
            "status_labels": dict(ATTENDANCE_STATUSES),
            "status_classes": ATTENDANCE_STATUS_CLASSES,
            "personale_filter": personale_id,
            "success_message": success_message,
            "error_message": error_message,
        },
        session,
        current_user,
    )


@router.post(
    "/manager/personale/presenze",
    response_class=HTMLResponse,
    name="manager_personale_presenze_update",
)
def manager_personale_presenze_update(
    request: Request,
    personale_id: int = Form(...),
    attendance_date: str = Form(...),
    status: str = Form(...),
    site_id: str = Form(""),
    hours: str = Form(""),
    week_start: str = Form(""),
    personale_filter: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    parsed_date = _parse_date(attendance_date)
    if not parsed_date:
        raise HTTPException(status_code=400, detail="Data non valida")

    parsed_site_id = _parse_int(site_id)
    parsed_hours = _parse_float(hours)
    redirect_week = _parse_date(week_start) or _get_week_start(None)
    redirect_personale = _parse_int(personale_filter)

    if status != "WORK":
        parsed_site_id = None

    upsert_personale_presenza(
        session=session,
        personale_id=personale_id,
        attendance_date=parsed_date,
        status=status,
        site_id=parsed_site_id,
        hours=parsed_hours,
    )
    session.commit()

    url = request.url_for("manager_personale_presenze")
    url = url.include_query_params(week_start=redirect_week.isoformat())
    if redirect_personale:
        url = url.include_query_params(personale_id=redirect_personale)
    return RedirectResponse(url=url, status_code=303)


@router.post(
    "/manager/personale/presenze/autofill",
    response_class=HTMLResponse,
    name="manager_personale_presenze_autofill",
)
def manager_personale_presenze_autofill(
    request: Request,
    personale_id: int = Form(...),
    week_start: str = Form(...),
    overwrite: bool = Form(False),
    personale_filter: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    parsed_week_start = _parse_date(week_start)
    if not parsed_week_start:
        raise HTTPException(status_code=400, detail="Data non valida")

    redirect_personale = _parse_int(personale_filter)

    created, updated, has_monday = copy_week_attendance_from_monday(
        session=session,
        personale_id=personale_id,
        week_start=parsed_week_start,
        overwrite=overwrite,
    )

    autofill_status = "success"
    if not has_monday:
        autofill_status = "missing"
    elif created == 0 and updated == 0:
        autofill_status = "noop"
    else:
        session.commit()

    url = request.url_for("manager_personale_presenze")
    url = url.include_query_params(week_start=parsed_week_start.isoformat())
    if redirect_personale:
        url = url.include_query_params(personale_id=redirect_personale)
    url = url.include_query_params(
        autofill=autofill_status, autofill_personale=personale_id
    )
    return RedirectResponse(url=url, status_code=303)
