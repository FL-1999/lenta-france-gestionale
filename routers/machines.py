import logging
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from auth import get_current_active_user_html
from database import get_db
from models import Machine, MachineTypeEnum, Site
from schemas import MachineCreate, MachineRead
from template_context import build_template_context, register_manager_badges
from permissions import has_perm

router = APIRouter()

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

MACHINE_STATUS_CHOICES = ["attivo", "manutenzione", "fuori_servizio"]
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100

perf_logger = logging.getLogger("lenta_france_gestionale.performance")


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _require_manager_or_admin(user):
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _get_machine_or_404(db: Session, machine_id: int) -> Machine:
    machine = db.query(Machine).filter(Machine.id == machine_id).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Macchinario non trovato")
    return machine


def _parse_site_id(site_id_value: str | None) -> int | None:
    if site_id_value in (None, ""):
        return None
    try:
        return int(site_id_value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Cantiere non valido")


# -------------------------------------------------
# API REST BASI /machines
# -------------------------------------------------

@router.post("/machines", response_model=MachineRead)
def create_machine_api(
    machine_in: MachineCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_active_user_html),
):
    _require_manager_or_admin(user)

    machine = Machine(
        name=machine_in.name,
        code=machine_in.code,
        machine_type=machine_in.machine_type,
        brand=machine_in.brand,
        model_name=machine_in.model_name,
        plate=machine_in.plate,
        status=machine_in.status,
        notes=machine_in.notes,
        site_id=machine_in.site_id,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@router.get("/machines", response_model=list[MachineRead])
def list_machines_api(
    db: Session = Depends(get_db),
    user=Depends(get_current_active_user_html),
):
    _require_manager_or_admin(user)
    machines = db.query(Machine).order_by(Machine.name.asc()).all()
    return machines


# -------------------------------------------------
# PAGINE MANAGER HTML
# -------------------------------------------------

@router.get(
    "/manager/macchinari",
    response_class=HTMLResponse,
    name="manager_machines_list",
)
def manager_machines_page(
    request: Request,
    current_user=Depends(get_current_active_user_html),
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    page, per_page = _normalize_pagination(page, per_page)
    total_count = db.query(func.count(Machine.id)).scalar() or 0
    query_started = time.monotonic()
    machines = (
        db.query(Machine)
        .options(
            load_only(
                Machine.id,
                Machine.name,
                Machine.code,
                Machine.brand,
                Machine.model_name,
                Machine.status,
            )
        )
        .order_by(Machine.name.asc(), Machine.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    perf_logger.debug(
        "manager_machines_list rows=%s total=%s page=%s per_page=%s duration_ms=%.2f",
        len(machines),
        total_count,
        page,
        per_page,
        (time.monotonic() - query_started) * 1000,
    )

    kpi_total = total_count
    kpi_active = (
        db.query(func.count(Machine.id))
        .filter(func.coalesce(Machine.status, "attivo") == "attivo")
        .scalar()
        or 0
    )
    kpi_oos = (
        db.query(func.count(Machine.id))
        .filter(Machine.status == "fuori_servizio")
        .scalar()
        or 0
    )

    return templates.TemplateResponse(
        "manager/macchinari_list.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            machines=machines,
            kpi_total=kpi_total,
            kpi_active=kpi_active,
            kpi_oos=kpi_oos,
            page=page,
            per_page=per_page,
            total_pages=max(1, (total_count + per_page - 1) // per_page),
        ),
    )


@router.get(
    "/manager/macchinari/nuovo",
    response_class=HTMLResponse,
    name="new_machine_form",
)
def manager_machine_new_get(
    request: Request,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    return templates.TemplateResponse(
        "manager/macchinari_form.html",
        build_template_context(
            request,
            current_user,
            current_user=current_user,
            is_edit=False,
            macchinario=None,
            machine_types=list(MachineTypeEnum),
            status_choices=MACHINE_STATUS_CHOICES,
            sites=sites,
        ),
    )


@router.post("/manager/macchinari/nuovo", name="create_machine")
def manager_machine_new_post(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    type: str | None = Form(None),
    brand: str | None = Form(None),
    model_name: str | None = Form(None),
    plate: str | None = Form(None),
    status: str = Form(...),
    notes: str | None = Form(None),
    site_id: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    machine_type = None
    if type:
        try:
            machine_type = MachineTypeEnum(type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Tipo macchinario non valido")

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    parsed_site_id = _parse_site_id(site_id)

    machine = Machine(
        code=code,
        name=name,
        machine_type=machine_type,
        brand=brand,
        model_name=model_name,
        plate=plate,
        status=status,
        notes=notes,
        site_id=parsed_site_id,
    )
    db.add(machine)
    db.commit()

    return RedirectResponse(url="/manager/macchinari", status_code=303)


@router.get(
    "/manager/macchinari/{machine_id}",
    response_class=HTMLResponse,
    name="manager_machine_detail",
)
def manager_machine_detail(
    request: Request,
    machine_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)

    return templates.TemplateResponse(
        "manager/macchinari_detail.html",
        build_template_context(
            request,
            current_user,
            macchinario=machine,
            current_user=current_user,
        ),
    )


@router.get(
    "/manager/macchinari/{machine_id}/modifica",
    response_class=HTMLResponse,
    name="manager_machine_edit",
)
def manager_machine_edit_get(
    request: Request,
    machine_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    return templates.TemplateResponse(
        "manager/macchinari_form.html",
        build_template_context(
            request,
            current_user,
            current_user=current_user,
            is_edit=True,
            macchinario=machine,
            machine_types=list(MachineTypeEnum),
            status_choices=MACHINE_STATUS_CHOICES,
            sites=sites,
        ),
    )


@router.post(
    "/manager/macchinari/{machine_id}/modifica",
    name="manager_machine_update",
)
def manager_machine_edit_post(
    request: Request,
    machine_id: int,
    code: str = Form(...),
    name: str = Form(...),
    type: str | None = Form(None),
    brand: str | None = Form(None),
    model_name: str | None = Form(None),
    plate: str | None = Form(None),
    status: str = Form(...),
    notes: str | None = Form(None),
    site_id: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)

    machine_type = None
    if type:
        try:
            machine_type = MachineTypeEnum(type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Tipo macchinario non valido")

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    machine.code = code
    machine.name = name
    machine.machine_type = machine_type
    machine.brand = brand
    machine.model_name = model_name
    machine.plate = plate
    machine.status = status
    machine.notes = notes
    machine.site_id = _parse_site_id(site_id)

    db.commit()

    return RedirectResponse(url=f"/manager/macchinari/{machine_id}", status_code=303)


@router.get("/manager/macchinari/assegna/{machine_id}", response_class=HTMLResponse)
def manager_machine_assign_get(
    request: Request,
    machine_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    return templates.TemplateResponse(
        "manager/macchinario_assegna.html",
        build_template_context(
            request,
            current_user,
            current_user=current_user,
            machine=machine,
            sites=sites,
        ),
    )


@router.post("/manager/macchinari/assegna/{machine_id}")
def manager_machine_assign_post(
    request: Request,
    machine_id: int,
    site_id: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)

    parsed_site_id = _parse_site_id(site_id)

    if parsed_site_id is not None:
        site = db.query(Site).filter(Site.id == parsed_site_id, Site.is_active == True).first()  # noqa: E712
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")
        machine.site_id = site.id
    else:
        machine.site_id = None

    db.commit()

    return RedirectResponse(url=f"/manager/macchinari/{machine_id}", status_code=303)
