import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from auth import get_current_active_user_html
from database import get_db
from models import Machine, MachineSiteAssignment, MachineTypeEnum, Site
from schemas import MachineCreate, MachineRead
from template_context import build_template_context, register_manager_badges
from permissions import has_perm

router = APIRouter()

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)

MACHINE_STATUS_CHOICES = [
    "attivo",
    "fuori_servizio",
    "deposito",
]
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


LOCATION_LABELS = {
    "__montauroux__": "Montauroux",
    "__st_jeannet__": "St. Jeannet",
    "__sommariva__": "Sommariva",
}


def _parse_site_selection(
    site_id_value: str | int | None,
) -> tuple[int | None, str | None]:
    if site_id_value in (None, ""):
        return None, None
    if isinstance(site_id_value, int):
        return site_id_value, None
    try:
        return int(site_id_value), None
    except (TypeError, ValueError):
        pass
    location_label = LOCATION_LABELS.get(str(site_id_value))
    if location_label is None:
        raise HTTPException(status_code=400, detail="Localizzazione non valida")
    return None, location_label


def _update_machine_assignment(
    db: Session,
    machine: Machine,
    site_id_value: str | int | None,
) -> None:
    site_id, location_label = _parse_site_selection(site_id_value)

    if site_id is not None:
        site = (
            db.query(Site)
            .filter(Site.id == site_id, Site.is_active == True)  # noqa: E712
            .first()
        )
        if not site:
            raise HTTPException(status_code=404, detail="Cantiere non trovato")

    now = datetime.utcnow()
    open_assignment = (
        db.query(MachineSiteAssignment)
        .filter(
            MachineSiteAssignment.machine_id == machine.id,
            MachineSiteAssignment.unassigned_at.is_(None),
        )
        .order_by(MachineSiteAssignment.assigned_at.desc())
        .first()
    )
    if open_assignment:
        open_assignment.unassigned_at = now

    if site_id is None and location_label is None:
        machine.site_id = None
        return

    machine.site_id = site_id
    assignment = MachineSiteAssignment(
        machine_id=machine.id,
        site_id=site_id,
        assigned_at=now,
        location_label=location_label,
    )
    db.add(assignment)


def _format_duration(delta: timedelta) -> str:
    total_seconds = max(int(delta.total_seconds()), 0)
    total_minutes = total_seconds // 60
    hours = total_minutes // 60
    days = hours // 24
    hours = hours % 24
    minutes = total_minutes % 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _build_assignment_rows(
    assignments: list[MachineSiteAssignment],
    now: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for assignment in assignments:
        end_time = assignment.unassigned_at or now
        duration = _format_duration(end_time - assignment.assigned_at)
        location = "—"
        if assignment.site:
            location = f"{assignment.site.name} ({assignment.site.code})"
        elif assignment.location_label:
            location = assignment.location_label
        rows.append(
            {
                "assigned_at": assignment.assigned_at,
                "unassigned_at": assignment.unassigned_at,
                "location": location,
                "duration": duration,
            }
        )
    return rows


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
        site_id=None,
    )
    db.add(machine)
    db.flush()
    _update_machine_assignment(db, machine, machine_in.site_id)
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

    machine = Machine(
        code=code,
        name=name,
        machine_type=machine_type,
        brand=brand,
        model_name=model_name,
        plate=plate,
        status=status,
        notes=notes,
        site_id=None,
    )
    db.add(machine)
    db.flush()
    _update_machine_assignment(db, machine, site_id)
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
    now = datetime.utcnow()
    assignment_rows = _build_assignment_rows(machine.assignments or [], now)

    return templates.TemplateResponse(
        "manager/macchinari_detail.html",
        build_template_context(
            request,
            current_user,
            macchinario=machine,
            assignment_rows=assignment_rows,
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
    _update_machine_assignment(db, machine, site_id)

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

    _update_machine_assignment(db, machine, site_id)

    db.commit()

    return RedirectResponse(url=f"/manager/macchinari/{machine_id}", status_code=303)
