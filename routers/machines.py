from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import Machine, MachineTypeEnum, RoleEnum, Site
from schemas import MachineCreate, MachineRead

router = APIRouter()

templates = Jinja2Templates(directory="templates")

MACHINE_STATUS_CHOICES = ["attivo", "manutenzione", "fuori_servizio"]


def _require_manager_or_admin(user):
    if user.role not in (RoleEnum.admin, RoleEnum.manager):
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
        machine_type=machine_in.machine_type,
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

@router.get("/manager/macchinari", response_class=HTMLResponse)
def manager_machines_page(
    request: Request,
    tipo: str | None = None,
    stato: str | None = None,
    cantiere: str | None = None,
    nome: str | None = None,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    query = db.query(Machine).outerjoin(Site)

    if tipo:
        try:
            tipo_enum = MachineTypeEnum(tipo)
            query = query.filter(Machine.machine_type == tipo_enum)
        except ValueError:
            pass

    if stato:
        query = query.filter(Machine.status == stato)

    parsed_cantiere = _parse_site_id(cantiere)

    if parsed_cantiere is not None:
        query = query.filter(Machine.site_id == parsed_cantiere)

    if nome:
        query = query.filter(Machine.name.ilike(f"%{nome}%"))

    machines = query.order_by(Machine.name.asc()).all()
    sites = db.query(Site).order_by(Site.name.asc()).all()

    return templates.TemplateResponse(
        "manager/macchinari.html",
        {
            "request": request,
            "machines": machines,
            "sites": sites,
            "current_user": current_user,
            "filter_type": tipo,
            "filter_status": stato,
            "filter_site": parsed_cantiere,
            "filter_name": nome,
            "status_choices": MACHINE_STATUS_CHOICES,
            "machine_types": list(MachineTypeEnum),
        },
    )


@router.get("/manager/macchinari/{machine_id}", response_class=HTMLResponse)
def manager_machine_detail(
    request: Request,
    machine_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)

    return templates.TemplateResponse(
        "manager/macchinario_dettaglio.html",
        {
            "request": request,
            "machine": machine,
            "current_user": current_user,
        },
    )


@router.get("/manager/macchinari/nuovo", response_class=HTMLResponse)
def manager_machine_new_get(
    request: Request,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    return templates.TemplateResponse(
        "manager/macchinario_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "machine": None,
            "machine_types": list(MachineTypeEnum),
            "status_choices": MACHINE_STATUS_CHOICES,
            "sites": sites,
        },
    )


@router.post("/manager/macchinari/nuovo")
def manager_machine_new_post(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    status: str = Form(...),
    notes: str | None = Form(None),
    site_id: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    try:
        machine_type = MachineTypeEnum(type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tipo macchinario non valido")

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    parsed_site_id = _parse_site_id(site_id)

    machine = Machine(
        name=name,
        machine_type=machine_type,
        status=status,
        notes=notes,
        site_id=parsed_site_id,
    )
    db.add(machine)
    db.commit()

    return RedirectResponse(url="/manager/macchinari", status_code=303)


@router.get("/manager/macchinari/modifica/{machine_id}", response_class=HTMLResponse)
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
        "manager/macchinario_form.html",
        {
            "request": request,
            "current_user": current_user,
            "mode": "edit",
            "machine": machine,
            "machine_types": list(MachineTypeEnum),
            "status_choices": MACHINE_STATUS_CHOICES,
            "sites": sites,
        },
    )


@router.post("/manager/macchinari/modifica/{machine_id}")
def manager_machine_edit_post(
    request: Request,
    machine_id: int,
    name: str = Form(...),
    type: str = Form(...),
    status: str = Form(...),
    notes: str | None = Form(None),
    site_id: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = _get_machine_or_404(db, machine_id)

    try:
        machine_type = MachineTypeEnum(type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Tipo macchinario non valido")

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    machine.name = name
    machine.machine_type = machine_type
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
        {
            "request": request,
            "current_user": current_user,
            "machine": machine,
            "sites": sites,
        },
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
