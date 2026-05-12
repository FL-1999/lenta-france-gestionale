import logging
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, load_only

from auth import get_current_active_user_html
from database import get_db
from models import Attrezzatura, Machine, MachineNote, MachineSiteAssignment, MachineType, MachineTypeEnum, MovimentoAttrezzatura, RoleEnum, Site
from schemas import MachineCreate, MachineRead
from template_context import build_template_context, register_manager_badges
from permissions import has_perm
from notifications import notify_machine_note_created

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
logger = logging.getLogger(__name__)


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


def _serialize_machine_types(
    machine_types: list[MachineType],
) -> list[dict[str, str | None]]:
    return [
        {
            "value": machine_type.code,
            "label_it": machine_type.label_it,
            "label_fr": machine_type.label_fr,
        }
        for machine_type in machine_types
    ]


def _build_machine_types_fallback() -> list[dict[str, str | None]]:
    return [
        {
            "value": machine_type.value,
            "label_it": None,
            "label_fr": None,
        }
        for machine_type in MachineTypeEnum
    ]


def _load_machine_types(db: Session) -> list[dict[str, str | None]]:
    try:
        machine_types_db = (
            db.query(MachineType)
            .filter(MachineType.is_active == True)  # noqa: E712
            .order_by(MachineType.label_it.asc())
            .all()
        )
    except SQLAlchemyError:
        machine_types_db = []

    if not machine_types_db:
        return _build_machine_types_fallback()
    return _serialize_machine_types(machine_types_db)


def _build_manager_machines_query(db: Session):
    return (
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
    )


def _build_machine_type_filters_by_code(
    machine_type_code: str,
    machine_type_enum: MachineTypeEnum | None,
) -> list:
    machine_type_value = machine_type_enum or machine_type_code
    return [
        or_(
            MachineType.code == machine_type_code,
            Machine.machine_type == machine_type_value,
        )
    ]


def _build_machine_type_counts(
    db: Session,
    machine_types: list[MachineType],
) -> dict[str, int]:
    type_id_to_code = {machine_type.id: machine_type.code for machine_type in machine_types}
    counts = {machine_type.code: 0 for machine_type in machine_types}
    machine_rows = db.query(Machine.machine_type_id, Machine.machine_type).all()
    for machine_type_id, machine_type_enum in machine_rows:
        if machine_type_id and machine_type_id in type_id_to_code:
            code = type_id_to_code[machine_type_id]
        elif machine_type_enum:
            code = machine_type_enum.value
        else:
            continue
        if code in counts:
            counts[code] += 1
    return counts


def _build_machine_type_filter_payload(
    machine_type_record: MachineType | None,
    machine_type_enum: MachineTypeEnum | None,
) -> dict[str, str | None]:
    code = None
    if machine_type_record:
        code = machine_type_record.code
    elif machine_type_enum:
        code = machine_type_enum.value
    return {
        "code": code,
        "label_it": machine_type_record.label_it if machine_type_record else None,
        "label_fr": machine_type_record.label_fr if machine_type_record else None,
    }


def _humanize_machine_type_code(code: str) -> str:
    cleaned = (code or "").strip().replace("_", " ")
    cleaned = " ".join(part for part in cleaned.split(" ") if part)
    return cleaned.title() if cleaned else "Tipologia"


def _build_machine_types_from_machines(db: Session) -> list[dict[str, str | int | None]]:
    types: dict[str, dict[str, str | int | None]] = {}
    machine_type_rows = (
        db.query(
            MachineType.code,
            MachineType.label_it,
            MachineType.label_fr,
            func.count(Machine.id),
        )
        .select_from(Machine)
        .outerjoin(MachineType, Machine.machine_type_id == MachineType.id)
        .filter(MachineType.code.isnot(None))
        .group_by(MachineType.code, MachineType.label_it, MachineType.label_fr)
        .all()
    )
    for code, label_it, label_fr, count in machine_type_rows:
        if not code:
            continue
        types[code] = {
            "code": code,
            "label_it": label_it or _humanize_machine_type_code(code),
            "label_fr": label_fr,
            "count": count,
        }

    enum_rows = (
        db.query(Machine.machine_type, func.count(Machine.id))
        .filter(Machine.machine_type.isnot(None))
        .group_by(Machine.machine_type)
        .all()
    )
    for machine_type_enum, count in enum_rows:
        if not machine_type_enum:
            continue
        code = machine_type_enum.value
        if code in types:
            types[code]["count"] = int(types[code]["count"] or 0) + count
            if not types[code].get("label_it"):
                types[code]["label_it"] = _humanize_machine_type_code(code)
        else:
            types[code] = {
                "code": code,
                "label_it": _humanize_machine_type_code(code),
                "label_fr": None,
                "count": count,
            }

    return sorted(types.values(), key=lambda item: (item.get("label_it") or item["code"]).lower())


def _resolve_machine_type(
    db: Session,
    type_value: str | None,
    reactivate: bool = False,
) -> tuple[MachineType | None, MachineTypeEnum | None]:
    type_value = (type_value or "").strip()
    if not type_value:
        return None, None

    # Lookup by code without filtering on is_active to preserve legacy/inactive entries.
    machine_type_record = db.query(MachineType).filter(MachineType.code == type_value).first()
    if machine_type_record and reactivate and not machine_type_record.is_active:
        machine_type_record.is_active = True
        db.add(machine_type_record)
        db.flush()
    machine_type_enum = None
    try:
        machine_type_enum = MachineTypeEnum(type_value)
    except ValueError:
        machine_type_enum = None
    return machine_type_record, machine_type_enum


def _snake_case(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return "tipologia"
    snake_chars: list[str] = []
    last_underscore = False
    for char in cleaned:
        if char.isalnum():
            snake_chars.append(char)
            last_underscore = False
        else:
            if not last_underscore:
                snake_chars.append("_")
                last_underscore = True
    snake = "".join(snake_chars).strip("_")
    return snake or "tipologia"


def _build_machine_type_redirect(
    redirect_to: str | None,
    machine_type_code: str,
) -> str:
    base_url = redirect_to if redirect_to and redirect_to.startswith("/") else "/manager/macchinari/nuovo"
    parsed = urlsplit(base_url)
    query_params = dict(parse_qsl(parsed.query))
    query_params["machine_type"] = machine_type_code
    updated_query = urlencode(query_params)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            updated_query,
            parsed.fragment,
        )
    )




NOTE_TYPE_CHOICES = (
    ("rottura", "Rottura"),
    ("manutenzione", "Manutenzione"),
    ("problema", "Problema"),
    ("osservazione", "Osservazione"),
)


def _require_capo(user):
    if user.role != RoleEnum.caposquadra:
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _get_capo_sites(db: Session, user) -> list[Site]:
    return (
        db.query(Site)
        .filter(Site.caposquadra_id == user.id, Site.is_active == True)  # noqa: E712
        .order_by(Site.name.asc())
        .all()
    )


def _latest_attrezzatura_movements_for_sites(db: Session, site_ids: list[int]) -> list[MovimentoAttrezzatura]:
    if not site_ids:
        return []
    latest_dates = (
        db.query(
            MovimentoAttrezzatura.attrezzatura_id.label("attrezzatura_id"),
            func.max(MovimentoAttrezzatura.data).label("latest_data"),
        )
        .group_by(MovimentoAttrezzatura.attrezzatura_id)
        .subquery()
    )
    return (
        db.query(MovimentoAttrezzatura)
        .options(
            joinedload(MovimentoAttrezzatura.attrezzatura),
            joinedload(MovimentoAttrezzatura.destinazione_site),
        )
        .join(
            latest_dates,
            and_(
                MovimentoAttrezzatura.attrezzatura_id == latest_dates.c.attrezzatura_id,
                MovimentoAttrezzatura.data == latest_dates.c.latest_data,
            ),
        )
        .filter(MovimentoAttrezzatura.destinazione_site_id.in_(site_ids))
        .order_by(MovimentoAttrezzatura.data.desc())
        .all()
    )


def _load_capo_asset(db: Session, user, asset_type: str, asset_id: int):
    sites = _get_capo_sites(db, user)
    site_ids = [site.id for site in sites]
    if asset_type == "machine":
        asset = (
            db.query(Machine)
            .options(joinedload(Machine.site), joinedload(Machine.machine_type_rel))
            .filter(Machine.id == asset_id, Machine.site_id.in_(site_ids))
            .first()
        )
        site = asset.site if asset else None
        label = asset.name if asset else ""
    elif asset_type == "attrezzatura":
        movement = (
            db.query(MovimentoAttrezzatura)
            .options(joinedload(MovimentoAttrezzatura.attrezzatura), joinedload(MovimentoAttrezzatura.destinazione_site))
            .filter(
                MovimentoAttrezzatura.attrezzatura_id == asset_id,
                MovimentoAttrezzatura.destinazione_site_id.in_(site_ids),
            )
            .order_by(MovimentoAttrezzatura.data.desc())
            .first()
        )
        asset = movement.attrezzatura if movement else None
        site = movement.destinazione_site if movement else None
        label = asset.nome if asset else ""
    else:
        raise HTTPException(status_code=404, detail="Risorsa non trovata")
    if not asset:
        raise HTTPException(status_code=404, detail="Risorsa non trovata o non assegnata")
    return asset, site, label


def _load_asset_notes(db: Session, asset_type: str, asset_id: int) -> list[MachineNote]:
    query = db.query(MachineNote).options(
        joinedload(MachineNote.operator),
        joinedload(MachineNote.site),
        joinedload(MachineNote.machine),
        joinedload(MachineNote.attrezzatura),
    )
    if asset_type == "machine":
        query = query.filter(MachineNote.machine_id == asset_id)
    elif asset_type == "attrezzatura":
        query = query.filter(MachineNote.attrezzatura_id == asset_id)
    else:
        raise HTTPException(status_code=404, detail="Risorsa non trovata")
    return query.order_by(MachineNote.created_at.desc()).all()


@router.get(
    "/capo/cantiere/attrezzature",
    response_class=HTMLResponse,
    name="capo_cantiere_attrezzature",
)
def capo_cantiere_attrezzature_page(
    request: Request,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_capo(current_user)
    sites = _get_capo_sites(db, current_user)
    site_ids = [site.id for site in sites]
    machines = []
    if site_ids:
        machines = (
            db.query(Machine)
            .options(joinedload(Machine.site), joinedload(Machine.machine_type_rel))
            .filter(Machine.site_id.in_(site_ids), Machine.is_active == True)  # noqa: E712
            .order_by(Machine.name.asc())
            .all()
        )
    attrezzatura_movements = _latest_attrezzatura_movements_for_sites(db, site_ids)

    return templates.TemplateResponse(
        request,
        "capo/cantiere_attrezzature.html",
        build_template_context(
            request,
            current_user,
            user_role="capo",
            sites=sites,
            machines=machines,
            attrezzatura_movements=attrezzatura_movements,
            success_message=request.query_params.get("success_message"),
            error_message=request.query_params.get("error_message"),
        ),
    )


@router.get(
    "/capo/cantiere/attrezzature/nota",
    response_class=HTMLResponse,
    name="capo_asset_note_form",
)
def capo_asset_note_form(
    request: Request,
    entity: str,
    asset_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_capo(current_user)
    asset, site, label = _load_capo_asset(db, current_user, entity, asset_id)
    return templates.TemplateResponse(
        request,
        "capo/asset_note_form.html",
        build_template_context(
            request,
            current_user,
            user_role="capo",
            entity=entity,
            asset=asset,
            site=site,
            asset_label=label,
            note_type_choices=NOTE_TYPE_CHOICES,
            error_message=request.query_params.get("error_message"),
        ),
    )


@router.post(
    "/capo/cantiere/attrezzature/nota",
    response_class=HTMLResponse,
    name="capo_asset_note_create",
)
def capo_asset_note_create(
    request: Request,
    entity: str = Form(...),
    asset_id: int = Form(...),
    note_text: str = Form(...),
    note_type: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_capo(current_user)
    text = (note_text or "").strip()
    if not text:
        return RedirectResponse(
            url=str(request.url_for("capo_asset_note_form")) + f"?entity={entity}&asset_id={asset_id}&error_message=Testo%20nota%20obbligatorio",
            status_code=303,
        )
    cleaned_type = (note_type or "").strip() or None
    allowed_types = {value for value, _label in NOTE_TYPE_CHOICES}
    if cleaned_type and cleaned_type not in allowed_types:
        cleaned_type = None

    asset, site, _label = _load_capo_asset(db, current_user, entity, asset_id)
    note = MachineNote(
        machine_id=asset.id if entity == "machine" else None,
        attrezzatura_id=asset.id if entity == "attrezzatura" else None,
        site_id=site.id if site else None,
        operator_id=current_user.id,
        note_type=cleaned_type,
        text=text,
    )
    db.add(note)
    db.flush()
    note = (
        db.query(MachineNote)
        .options(joinedload(MachineNote.machine), joinedload(MachineNote.attrezzatura), joinedload(MachineNote.site))
        .filter(MachineNote.id == note.id)
        .one()
    )
    notify_machine_note_created(db, note, current_user)
    db.commit()
    return RedirectResponse(
        url=str(request.url_for("capo_cantiere_attrezzature")) + "?success_message=Nota%20aggiunta",
        status_code=303,
    )


@router.get(
    "/capo/cantiere/attrezzature/note",
    response_class=HTMLResponse,
    name="capo_asset_notes_history",
)
def capo_asset_notes_history(
    request: Request,
    entity: str,
    asset_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_capo(current_user)
    asset, site, label = _load_capo_asset(db, current_user, entity, asset_id)
    notes = _load_asset_notes(db, entity, asset.id)
    return templates.TemplateResponse(
        request,
        "manager/machine_notes_history.html",
        build_template_context(
            request,
            current_user,
            user_role="capo",
            entity=entity,
            asset=asset,
            site=site,
            asset_label=label,
            notes=notes,
            back_url=request.url_for("capo_cantiere_attrezzature"),
        ),
    )


@router.get(
    "/manager/macchinari/{machine_id}/note",
    response_class=HTMLResponse,
    name="manager_machine_notes_history",
)
def manager_machine_notes_history(
    request: Request,
    machine_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    machine = (
        db.query(Machine)
        .options(joinedload(Machine.site), joinedload(Machine.machine_type_rel))
        .filter(Machine.id == machine_id)
        .first()
    )
    if not machine:
        raise HTTPException(status_code=404, detail="Macchinario non trovato")
    notes = _load_asset_notes(db, "machine", machine.id)
    return templates.TemplateResponse(
        request,
        "manager/machine_notes_history.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            entity="machine",
            asset=machine,
            site=machine.site,
            asset_label=machine.name,
            notes=notes,
            back_url=request.url_for("manager_machines_list"),
        ),
    )


@router.get(
    "/manager/attrezzature/{attrezzatura_id}/note",
    response_class=HTMLResponse,
    name="manager_attrezzatura_notes_history",
)
def manager_attrezzatura_notes_history(
    request: Request,
    attrezzatura_id: int,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.id == attrezzatura_id).first()
    if not attrezzatura:
        raise HTTPException(status_code=404, detail="Attrezzatura non trovata")
    notes = _load_asset_notes(db, "attrezzatura", attrezzatura.id)
    latest_note_site = notes[0].site if notes else None
    return templates.TemplateResponse(
        request,
        "manager/machine_notes_history.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            entity="attrezzatura",
            asset=attrezzatura,
            site=latest_note_site,
            asset_label=attrezzatura.nome,
            notes=notes,
            back_url=request.url_for("manager_machines_list"),
        ),
    )


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
    base_query = _build_manager_machines_query(db)
    total_count = base_query.with_entities(func.count(Machine.id)).order_by(None).scalar() or 0
    query_started = time.monotonic()
    machines = (
        base_query
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
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    success_message = request.query_params.get("success_message")
    error_message = request.query_params.get("error_message")

    return templates.TemplateResponse(
        request,
        "manager/macchinari_list.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            machines=machines,
            kpi_total=kpi_total,
            kpi_active=kpi_active,
            kpi_oos=kpi_oos,
            sites=sites,
            page=page,
            per_page=per_page,
            total_pages=max(1, (total_count + per_page - 1) // per_page),
            success_message=success_message,
            error_message=error_message,
        ),
    )


@router.get(
    "/manager/macchinari/tipologie",
    response_class=HTMLResponse,
    name="manager_machine_types_list",
)
def manager_machine_types_page(
    request: Request,
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    tipologie = _build_machine_types_from_machines(db)

    return templates.TemplateResponse(
        request,
        "manager/macchinari_tipologie_list.html",
        build_template_context(
            request,
            current_user,
            tipologie=tipologie,
        ),
    )


@router.get(
    "/manager/macchinari/tipologie/{code}",
    response_class=HTMLResponse,
    name="manager_machine_types_detail",
)
def manager_machine_types_detail_page(
    request: Request,
    code: str,
    current_user=Depends(get_current_active_user_html),
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    page, per_page = _normalize_pagination(page, per_page)
    machine_type_record, machine_type_enum = _resolve_machine_type(db, code)
    machine_type_filters = []
    if code:
        machine_type_filters = _build_machine_type_filters_by_code(
            code,
            machine_type_enum,
        )
    active_machine_type_count = (
        db.query(func.count(MachineType.id))
        .filter(MachineType.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )
    logger.info(
        "manager_machine_types_detail pre-query code=%s machine_type_id=%s active_types=%s",
        code,
        machine_type_record.id if machine_type_record else None,
        active_machine_type_count,
    )
    logger.info(
        "manager_machine_types_detail code=%s filters=%s",
        code,
        machine_type_filters,
    )
    base_query = _build_manager_machines_query(db)
    if machine_type_filters:
        base_query = (
            base_query
            .outerjoin(MachineType, Machine.machine_type_id == MachineType.id)
            .filter(*machine_type_filters)
        )
    total_count = base_query.with_entities(func.count(Machine.id)).order_by(None).scalar() or 0
    logger.info("manager_machine_types_detail count=%s", total_count)
    query_started = time.monotonic()
    machines = (
        base_query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    sample_machines = base_query.limit(10).all()
    perf_logger.debug(
        "manager_machines_list rows=%s total=%s page=%s per_page=%s duration_ms=%.2f",
        len(machines),
        total_count,
        page,
        per_page,
        (time.monotonic() - query_started) * 1000,
    )
    logger.info(
        "manager_machine_types_detail post-query count=%s sample=%s",
        total_count,
        [
            (machine.id, machine.machine_type_id, machine.machine_type)
            for machine in sample_machines
        ],
    )

    kpi_total = total_count
    kpi_base_query = db.query(func.count(Machine.id))
    if machine_type_filters:
        kpi_base_query = (
            kpi_base_query
            .outerjoin(MachineType, Machine.machine_type_id == MachineType.id)
            .filter(*machine_type_filters)
        )
    kpi_active = (
        kpi_base_query
        .filter(func.coalesce(Machine.status, "attivo") == "attivo")
        .scalar()
        or 0
    )
    kpi_oos = (
        kpi_base_query
        .filter(Machine.status == "fuori_servizio")
        .scalar()
        or 0
    )
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name.asc()).all()  # noqa: E712

    success_message = request.query_params.get("success_message")
    error_message = request.query_params.get("error_message")
    machine_type_filter = _build_machine_type_filter_payload(
        machine_type_record,
        machine_type_enum,
    )

    return templates.TemplateResponse(
        request,
        "manager/macchinari_list.html",
        build_template_context(
            request,
            current_user,
            user_role="manager",
            machines=machines,
            kpi_total=kpi_total,
            kpi_active=kpi_active,
            kpi_oos=kpi_oos,
            sites=sites,
            page=page,
            per_page=per_page,
            total_pages=max(1, (total_count + per_page - 1) // per_page),
            success_message=success_message,
            error_message=error_message,
            machine_type_filter=machine_type_filter,
            is_machine_type_detail=True,
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
    machine_types = _load_machine_types(db)
    selected_machine_type = request.query_params.get("machine_type")

    return templates.TemplateResponse(
        request,
        "manager/macchinari_form.html",
        build_template_context(
            request,
            current_user,
            current_user=current_user,
            is_edit=False,
            macchinario=None,
            machine_types=machine_types,
            status_choices=MACHINE_STATUS_CHOICES,
            sites=sites,
            selected_machine_type=selected_machine_type,
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

    machine_type_record, machine_type_enum = _resolve_machine_type(db, type, reactivate=True)

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    machine = Machine(
        code=code,
        name=name,
        machine_type=machine_type_enum,
        machine_type_id=machine_type_record.id if machine_type_record else None,
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
    logger.info(
        "create_machine pre-commit type=%s machine_type_id=%s machine_type=%s",
        type,
        machine.machine_type_id,
        machine.machine_type,
    )
    db.commit()
    db.refresh(machine)
    logger.info(
        "create_machine post-commit id=%s machine_type_id=%s machine_type=%s",
        machine.id,
        machine.machine_type_id,
        machine.machine_type,
    )

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
        request,
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
    machine_types = _load_machine_types(db)
    selected_machine_type = request.query_params.get("machine_type")

    return templates.TemplateResponse(
        request,
        "manager/macchinari_form.html",
        build_template_context(
            request,
            current_user,
            current_user=current_user,
            is_edit=True,
            macchinario=machine,
            machine_types=machine_types,
            status_choices=MACHINE_STATUS_CHOICES,
            sites=sites,
            selected_machine_type=selected_machine_type,
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

    machine_type_record, machine_type_enum = _resolve_machine_type(db, type, reactivate=True)

    if status not in MACHINE_STATUS_CHOICES:
        raise HTTPException(status_code=400, detail="Stato macchinario non valido")

    machine.code = code
    machine.name = name
    machine.machine_type = machine_type_enum
    machine.machine_type_id = machine_type_record.id if machine_type_record else None
    machine.brand = brand
    machine.model_name = model_name
    machine.plate = plate
    machine.status = status
    machine.notes = notes
    _update_machine_assignment(db, machine, site_id)

    logger.info(
        "manager_machine_update pre-commit type=%s machine_type_id=%s machine_type=%s",
        type,
        machine.machine_type_id,
        machine.machine_type,
    )
    db.commit()
    db.refresh(machine)
    logger.info(
        "manager_machine_update post-commit id=%s machine_type_id=%s machine_type=%s",
        machine.id,
        machine.machine_type_id,
        machine.machine_type,
    )

    return RedirectResponse(url=f"/manager/macchinari/{machine_id}", status_code=303)


@router.post("/manager/machine-types", name="manager_machine_type_create")
def manager_machine_type_create(
    request: Request,
    label_it: str = Form(...),
    label_fr: str | None = Form(None),
    redirect_to: str | None = Form(None),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)

    label_it_value = (label_it or "").strip()
    if not label_it_value:
        raise HTTPException(status_code=400, detail="La tipologia è obbligatoria.")

    label_fr_value = (label_fr or "").strip() or None
    code = _snake_case(label_it_value)

    machine_type = db.query(MachineType).filter(MachineType.code == code).first()
    if machine_type is None:
        machine_type = MachineType(
            code=code,
            label_it=label_it_value,
            label_fr=label_fr_value,
            is_active=True,
        )
        db.add(machine_type)
    elif not machine_type.is_active:
        machine_type.is_active = True
        db.add(machine_type)

    db.commit()
    db.refresh(machine_type)

    redirect_url = _build_machine_type_redirect(redirect_to, machine_type.code)
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post(
    "/manager/macchinari/{machine_id}/quick-update",
    name="manager_machine_quick_update",
)
def manager_machine_quick_update(
    request: Request,
    machine_id: int,
    status: str = Form(...),
    location: str | None = Form(""),
    current_user=Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    _require_manager_or_admin(current_user)
    error_message = None

    try:
        machine = _get_machine_or_404(db, machine_id)
        if status not in MACHINE_STATUS_CHOICES:
            raise HTTPException(status_code=400, detail="Stato macchinario non valido")

        site_id, location_label = _parse_site_selection(location)
        if site_id is not None:
            site = (
                db.query(Site)
                .filter(Site.id == site_id, Site.is_active == True)  # noqa: E712
                .first()
            )
            if not site:
                raise HTTPException(status_code=404, detail="Cantiere non trovato")

        machine.status = status
        has_history = (
            db.query(MachineSiteAssignment.id)
            .filter(MachineSiteAssignment.machine_id == machine.id)
            .first()
            is not None
        )
        if has_history:
            _update_machine_assignment(db, machine, location)
        else:
            machine.site_id = site_id
            if location_label is not None:
                machine.site_id = None

        db.commit()
        success_message = "Aggiornato"
    except HTTPException as exc:
        db.rollback()
        error_message = exc.detail or "Errore"
        success_message = None

    base_url = str(request.url_for("manager_machines_list"))
    params = {}
    if error_message:
        params["error_message"] = error_message
    else:
        params["success_message"] = success_message or "Aggiornato"

    url = f"{base_url}?{urlencode(params)}" if params else base_url
    return RedirectResponse(url=url, status_code=303)


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
        request,
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
