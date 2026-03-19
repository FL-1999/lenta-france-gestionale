from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import (
    Attrezzatura,
    AttrezzaturaStatoEnum,
    Depot,
    MovimentoAttrezzatura,
    Role,
    RoleEnum,
    UserRole,
    Site,
    TrasportoAttrezzaturaViaggio,
    TrasportoRichiestaAttrezzatura,
    TrasportoStatoEnum,
    TrasportoTappa,
    TrasportoViaggio,
    User,
)
from models.veicoli import Veicolo
from permissions import can_access_logistics_area, can_access_manager_area, can_manage_trip_loads, has_perm
from template_context import register_manager_badges, render_template
from utils.places import format_place_label, get_place_by_value, get_selectable_places

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["trasporti"])

WEEKDAY_LABELS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _ensure_logistics_access(user: User) -> None:
    if not can_access_logistics_area(user):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_manager(user: User) -> None:
    if not can_access_manager_area(user):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_trip_load_operator(user: User) -> None:
    if not can_manage_trip_loads(user):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_driver(user: User) -> None:
    if not has_perm(user, "trasporti.assigned.read"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli autisti")


def _load_trip_form_dependencies(db: Session) -> tuple[list[User], list[Veicolo], list]:
    autisti = (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(Role.name == RoleEnum.driver, User.is_active.is_(True))
        .distinct()
        .order_by(User.full_name, User.email)
        .all()
    )
    mezzi = (
        db.query(Veicolo)
        .filter(Veicolo.visibile_trasporti.is_(True))
        .order_by(Veicolo.marca.asc(), Veicolo.modello.asc(), Veicolo.targa.asc())
        .all()
    )
    luoghi = get_selectable_places(db, include_inactive=False)
    return autisti, mezzi, luoghi


def _apply_trip_place(viaggio: TrasportoViaggio, field_name: str, place) -> None:
    setattr(viaggio, field_name, place.name)
    setattr(viaggio, f"{field_name}_site_id", place.id if place.kind == "site" else None)
    setattr(viaggio, f"{field_name}_depot_id", place.id if place.kind == "depot" else None)


def _trip_place_value(viaggio: TrasportoViaggio | None, field_name: str) -> str:
    if not viaggio:
        return ""
    site_id = getattr(viaggio, f"{field_name}_site_id", None)
    depot_id = getattr(viaggio, f"{field_name}_depot_id", None)
    if site_id:
        return f"site:{site_id}"
    if depot_id:
        return f"depot:{depot_id}"
    return ""


def _trip_place_label(viaggio: TrasportoViaggio, field_name: str) -> str:
    site = getattr(viaggio, f"{field_name}_site", None)
    depot = getattr(viaggio, f"{field_name}_depot", None)
    legacy_value = getattr(viaggio, field_name, None)
    if site:
        return format_place_label("site", site.name)
    if depot:
        return format_place_label("depot", depot.name)
    return legacy_value or "—"


def _stop_place_value(tappa: TrasportoTappa | None) -> str:
    if not tappa:
        return ""
    if tappa.site_id:
        return f"site:{tappa.site_id}"
    if tappa.depot_id:
        return f"depot:{tappa.depot_id}"
    return ""


def _stop_place_label(tappa: TrasportoTappa) -> str:
    if tappa.site:
        return format_place_label("site", tappa.site.name)
    if tappa.depot:
        return format_place_label("depot", tappa.depot.name)
    return tappa.destinazione or "—"


def _movement_place_label(movimento: MovimentoAttrezzatura, field_name: str) -> str:
    site = getattr(movimento, f"{field_name}_site", None)
    depot = getattr(movimento, f"{field_name}_depot", None)
    legacy_value = getattr(movimento, field_name, None)
    if site:
        return format_place_label("site", site.name)
    if depot:
        return format_place_label("depot", depot.name)
    return legacy_value or "—"


def _decorate_trip_locations(viaggio: TrasportoViaggio) -> TrasportoViaggio:
    viaggio.origine_label = _trip_place_label(viaggio, "origine")
    viaggio.destinazione_label = _trip_place_label(viaggio, "destinazione")
    for tappa in viaggio.tappe or []:
        tappa.destinazione_label = _stop_place_label(tappa)
    return viaggio


def _trip_missing_equipment_alerts(viaggi: list[TrasportoViaggio]) -> list[dict[str, object]]:
    alerts = []
    for viaggio in viaggi:
        ass_by_type: dict[str, int] = {}
        for ass in viaggio.assegnazioni_attrezzature:
            key = (ass.attrezzatura.tipo or "").strip().lower()
            if not key:
                continue
            ass_by_type[key] = ass_by_type.get(key, 0) + 1

        missing_types = []
        for req in viaggio.richieste_attrezzature:
            req_key = (req.tipo_attrezzatura or "").strip().lower()
            selected = ass_by_type.get(req_key, 0)
            if selected < req.quantita:
                missing_types.append(req.tipo_attrezzatura)

        if missing_types:
            alerts.append(
                {
                    "trip_id": viaggio.id,
                    "trip_code": viaggio.codice_viaggio,
                    "missing_types": missing_types,
                    "message": "Attrezzatura mancante",
                }
            )
    return alerts


@router.get("/manager/trasporti", response_class=HTMLResponse, name="manager_trasporti_dashboard")
def manager_trasporti_dashboard(
    request: Request,
    autista_id: int | None = None,
    mezzo_id: int | None = None,
    stato: str | None = None,
    destinazione: str | None = None,
    data: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    today = date.today()
    selected_stato = None
    if stato:
        try:
            selected_stato = TrasportoStatoEnum(stato)
        except ValueError:
            selected_stato = None

    selected_data = None
    if data:
        try:
            selected_data = datetime.strptime(data, "%Y-%m-%d").date()
        except ValueError:
            selected_data = None

    def _apply_filters(query):
        if autista_id:
            query = query.filter(TrasportoViaggio.autista_id == autista_id)
        if mezzo_id:
            query = query.filter(TrasportoViaggio.mezzo_id == mezzo_id)
        if selected_stato:
            query = query.filter(TrasportoViaggio.stato == selected_stato)
        if destinazione:
            pattern = f"%{destinazione.strip()}%"
            query = query.filter((TrasportoViaggio.destinazione.ilike(pattern)) | (TrasportoViaggio.tappe.any(TrasportoTappa.destinazione.ilike(pattern))))
        if selected_data:
            query = query.filter(TrasportoViaggio.data_partenza == selected_data)
        return query

    base_query = db.query(TrasportoViaggio).options(
        joinedload(TrasportoViaggio.autista),
        joinedload(TrasportoViaggio.mezzo),
        joinedload(TrasportoViaggio.origine_site),
        joinedload(TrasportoViaggio.origine_depot),
        joinedload(TrasportoViaggio.destinazione_site),
        joinedload(TrasportoViaggio.destinazione_depot),
        joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
        joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
        joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
        joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
    )

    future_trips = (
        _apply_filters(base_query.filter(TrasportoViaggio.data_partenza >= today))
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
    active_trips = (
        _apply_filters(
            base_query.filter(
                TrasportoViaggio.stato.in_(
                    [TrasportoStatoEnum.in_carico, TrasportoStatoEnum.in_viaggio, TrasportoStatoEnum.arrivato]
                )
            )
        )
        .order_by(TrasportoViaggio.data_partenza.desc())
        .all()
    )
    completed_trips = (
        _apply_filters(base_query.filter(TrasportoViaggio.stato == TrasportoStatoEnum.completato))
        .order_by(TrasportoViaggio.data_partenza.desc())
        .limit(20)
        .all()
    )
    autisti = db.query(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).filter(Role.name == RoleEnum.driver).distinct().order_by(User.full_name, User.email).all()
    mezzi = db.query(Veicolo).filter(Veicolo.visibile_trasporti.is_(True)).order_by(Veicolo.marca, Veicolo.modello).all()
    future_trips = [_decorate_trip_locations(viaggio) for viaggio in future_trips]
    active_trips = [_decorate_trip_locations(viaggio) for viaggio in active_trips]
    completed_trips = [_decorate_trip_locations(viaggio) for viaggio in completed_trips]
    equipment_alerts = _trip_missing_equipment_alerts(future_trips + active_trips)
    logistics_overview = {
        "trucks_in_travel": sum(1 for trip in active_trips if trip.stato == TrasportoStatoEnum.in_viaggio),
        "equipment_moving": db.query(func.count(Attrezzatura.id)).filter(Attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto).scalar()
        or 0,
        "active_trips": len(active_trips),
        "alerts": len(equipment_alerts),
    }
    return render_template(
        templates,
        request,
        "manager/trasporti/dashboard.html",
        {
            "future_trips": future_trips,
            "active_trips": active_trips,
            "completed_trips": completed_trips,
            "autisti": autisti,
            "mezzi": mezzi,
            "stati": list(TrasportoStatoEnum),
            "equipment_alerts": equipment_alerts,
            "logistics_overview": logistics_overview,
            "filters": {
                "autista_id": autista_id,
                "mezzo_id": mezzo_id,
                "stato": selected_stato.value if selected_stato else "",
                "destinazione": destinazione or "",
                "data": data or "",
            },
        },
        db,
        current_user,
    )


@router.get("/manager/trasporti/planner", response_class=HTMLResponse, name="manager_trasporti_planner")
def manager_trasporti_planner(
    request: Request,
    week_start: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    _ensure_manager(current_user)
    if week_start:
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
    else:
        today = date.today()
        start = today - timedelta(days=today.weekday())
    week_dates = [start + timedelta(days=i) for i in range(7)]

    mezzi = db.query(Veicolo).filter(Veicolo.visibile_trasporti.is_(True)).order_by(Veicolo.marca, Veicolo.modello).all()
    viaggi = (
        db.query(TrasportoViaggio)
        .filter(TrasportoViaggio.data_partenza >= week_dates[0], TrasportoViaggio.data_partenza <= week_dates[-1])
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
    trips_by_mezzo_date: dict[tuple[int, date], list[TrasportoViaggio]] = {}
    unassigned_by_date: dict[date, list[TrasportoViaggio]] = {d: [] for d in week_dates}
    for trip in viaggi:
        if trip.mezzo_id:
            key = (trip.mezzo_id, trip.data_partenza)
            trips_by_mezzo_date.setdefault(key, []).append(trip)
        else:
            unassigned_by_date.setdefault(trip.data_partenza, []).append(trip)

    return render_template(
        templates,
        request,
        "manager/trasporti/planner.html",
        {
            "mezzi": mezzi,
            "week_dates": week_dates,
            "weekday_labels": WEEKDAY_LABELS,
            "trips_by_mezzo_date": trips_by_mezzo_date,
            "unassigned_by_date": unassigned_by_date,
            "prev_week": (start - timedelta(days=7)).isoformat(),
            "next_week": (start + timedelta(days=7)).isoformat(),
        },
        db,
        current_user,
    )


@router.post("/manager/trasporti/viaggi/{viaggio_id}/sposta-data", name="manager_trasporti_viaggi_move_date")
def manager_trasporti_viaggi_move_date(
    viaggio_id: int,
    request: Request,
    target_date: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id).first()
    if viaggio:
        viaggio.data_partenza = datetime.strptime(target_date, "%Y-%m-%d").date()
        db.commit()
    redirect_week = request.query_params.get("week_start") or target_date
    return RedirectResponse(url=f"{request.url_for('manager_trasporti_planner')}?week_start={redirect_week}", status_code=303)


@router.get("/manager/trasporti/mappa", response_class=HTMLResponse, name="manager_trasporti_mappa")
def manager_trasporti_mappa(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    _ensure_manager(current_user)
    sites = (
        db.query(Site)
        .filter(Site.lat.isnot(None), Site.lng.isnot(None), Site.is_active.is_(True))
        .order_by(Site.name.asc())
        .all()
    )
    depots = (
        db.query(Depot)
        .filter(Depot.lat.isnot(None), Depot.lng.isnot(None), Depot.is_active.is_(True))
        .order_by(Depot.name.asc())
        .all()
    )
    place_map = {f"site:{site.id}": site for site in sites}
    place_map.update({f"depot:{depot.id}": depot for depot in depots})

    trucks_in_travel = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
        )
        .filter(TrasportoViaggio.stato == TrasportoStatoEnum.in_viaggio)
        .all()
    )

    truck_markers = []
    equipment_markers = []
    for trip in trucks_in_travel:
        _decorate_trip_locations(trip)
        origin_place = place_map.get(_trip_place_value(trip, "origine"))
        dest_place = place_map.get(_trip_place_value(trip, "destinazione"))
        if origin_place and dest_place:
            lat = (origin_place.lat + dest_place.lat) / 2
            lng = (origin_place.lng + dest_place.lng) / 2
        elif dest_place:
            lat, lng = dest_place.lat, dest_place.lng
        elif origin_place:
            lat, lng = origin_place.lat, origin_place.lng
        else:
            continue
        truck_markers.append(
            {
                "lat": float(lat),
                "lng": float(lng),
                "label": f"{trip.codice_viaggio} - {trip.origine_label} → {trip.destinazione_label}",
                "detail_url": str(request.url_for("manager_trasporti_viaggi_detail", viaggio_id=trip.id)),
            }
        )
        for ass in trip.assegnazioni_attrezzature:
            equipment_markers.append(
                {
                    "lat": float(lat),
                    "lng": float(lng),
                    "label": f"{ass.attrezzatura.codice} ({ass.attrezzatura.tipo}) su {trip.codice_viaggio}",
                    "detail_url": str(request.url_for("manager_trasporti_viaggi_detail", viaggio_id=trip.id)),
                }
            )

    site_markers = [
        {
            "lat": float(s.lat),
            "lng": float(s.lng),
            "label": format_place_label("site", s.name),
            "detail_url": str(request.url_for("manager_site_detail", site_id=s.id)),
        }
        for s in sites
    ]
    site_markers.extend(
        {
            "lat": float(d.lat),
            "lng": float(d.lng),
            "label": format_place_label("depot", d.name),
            "detail_url": str(request.url_for("manager_depositi_edit", depot_id=d.id)),
        }
        for d in depots
    )

    return render_template(
        templates,
        request,
        "manager/trasporti/mappa.html",
        {"site_markers": site_markers, "truck_markers": truck_markers, "equipment_markers": equipment_markers},
        db,
        current_user,
    )


@router.get(
    "/manager/trasporti/attrezzature-in-viaggio",
    response_class=HTMLResponse,
    name="manager_trasporti_attrezzature_in_viaggio",
)
def manager_trasporti_attrezzature_in_viaggio(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    assignments = (
        db.query(TrasportoAttrezzaturaViaggio)
        .options(
            joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.autista),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.destinazione_depot),
        )
        .join(TrasportoAttrezzaturaViaggio.attrezzatura)
        .filter(Attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto)
        .all()
    )
    for assignment in assignments:
        if assignment.viaggio:
            _decorate_trip_locations(assignment.viaggio)
    return render_template(
        templates,
        request,
        "manager/trasporti/attrezzature_in_viaggio.html",
        {"assignments": assignments},
        db,
        current_user,
    )


@router.get("/manager/trasporti/nuovo", response_class=HTMLResponse)
@router.get("/manager/trasporti/viaggi/nuovo", response_class=HTMLResponse, name="manager_trasporti_viaggi_new")
def manager_trasporti_viaggi_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    autisti, mezzi, luoghi = _load_trip_form_dependencies(db)
    return render_template(
        templates,
        request,
        "manager/trasporti/new_trip.html",
        {
            "autisti": autisti,
            "mezzi": mezzi,
            "locations": luoghi,
            "mode": "create",
            "viaggio": None,
            "form_action": request.url_for("manager_trasporti_viaggi_create"),
            "form_data": {
                "codice_viaggio": "",
                "data_partenza": "",
                "data_arrivo_prevista": "",
                "autista_id": "",
                "mezzo_id": "",
                "origine_place": "",
                "destinazione_place": "",
                "tappa_destinazione": ["", "", ""],
                "tipo_attrezzatura": ["", "", ""],
                "quantita": ["1", "1", "1"],
                "richiesta_tappa_idx": ["1", "1", "1"],
            },
        },
        db,
        current_user,
    )


@router.post("/manager/trasporti/nuovo", response_class=HTMLResponse)
@router.post("/manager/trasporti/viaggi/nuovo", response_class=HTMLResponse, name="manager_trasporti_viaggi_create")
def manager_trasporti_viaggi_create(
    request: Request,
    codice_viaggio: str = Form(...),
    data_partenza: str = Form(...),
    data_arrivo_prevista: str | None = Form(None),
    autista_id: int | None = Form(None),
    mezzo_id: int | None = Form(None),
    origine_place: str = Form(...),
    destinazione_place: str = Form(...),
    tappa_destinazione: list[str] = Form(default=[]),
    tipo_attrezzatura: list[str] = Form(default=[]),
    quantita: list[str] = Form(default=[]),
    richiesta_tappa_idx: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    autisti, mezzi, luoghi = _load_trip_form_dependencies(db)
    form_data = {
        "codice_viaggio": codice_viaggio,
        "data_partenza": data_partenza,
        "data_arrivo_prevista": data_arrivo_prevista or "",
        "autista_id": str(autista_id or ""),
        "mezzo_id": str(mezzo_id or ""),
        "origine_place": origine_place,
        "destinazione_place": destinazione_place,
        "tappa_destinazione": tappa_destinazione,
        "tipo_attrezzatura": tipo_attrezzatura,
        "quantita": quantita,
        "richiesta_tappa_idx": richiesta_tappa_idx,
    }
    origine_obj = get_place_by_value(db, origine_place, include_inactive=False)
    destinazione_obj = get_place_by_value(db, destinazione_place, include_inactive=False)
    if not origine_obj or not destinazione_obj:
        return render_template(
            templates,
            request,
            "manager/trasporti/new_trip.html",
            {
                "autisti": autisti,
                "mezzi": mezzi,
                "locations": luoghi,
                "mode": "create",
                "viaggio": None,
                "form_action": request.url_for("manager_trasporti_viaggi_create"),
                "form_data": form_data,
                "error_message": "Seleziona origine e destinazione da un luogo esistente.",
            },
            db,
            current_user,
            status_code=400,
        )
    viaggio = TrasportoViaggio(
        codice_viaggio=codice_viaggio.strip().upper(),
        data_partenza=datetime.strptime(data_partenza, "%Y-%m-%d").date(),
        data_arrivo_prevista=datetime.strptime(data_arrivo_prevista, "%Y-%m-%d").date() if data_arrivo_prevista else None,
        autista_id=autista_id,
        mezzo_id=mezzo_id,
        origine=origine_obj.name,
        destinazione=destinazione_obj.name,
        stato=TrasportoStatoEnum.programmato,
    )
    _apply_trip_place(viaggio, "origine", origine_obj)
    _apply_trip_place(viaggio, "destinazione", destinazione_obj)
    db.add(viaggio)
    db.flush()

    tappe_clean = [get_place_by_value(db, raw, include_inactive=False) for raw in tappa_destinazione if (raw or "").strip()]
    tappe_clean = [tappa for tappa in tappe_clean if tappa is not None]
    if not tappe_clean:
        tappe_clean = [destinazione_obj]

    tappe: list[TrasportoTappa] = []
    for idx, place in enumerate(tappe_clean, start=1):
        tappa = TrasportoTappa(
            viaggio_id=viaggio.id,
            ordine=idx,
            destinazione=place.name,
            site_id=place.id if place.kind == "site" else None,
            depot_id=place.id if place.kind == "depot" else None,
        )
        db.add(tappa)
        tappe.append(tappa)
    db.flush()

    for idx, tipo in enumerate(tipo_attrezzatura):
        tipo_clean = (tipo or "").strip().lower()
        if not tipo_clean:
            continue
        q_raw = quantita[idx] if idx < len(quantita) else "1"
        q = max(1, int(q_raw or 1))
        tappa_idx_raw = richiesta_tappa_idx[idx] if idx < len(richiesta_tappa_idx) else "1"
        tappa_idx = max(1, int(tappa_idx_raw or 1))
        tappa = tappe[tappa_idx - 1] if tappa_idx <= len(tappe) else tappe[-1]
        db.add(
            TrasportoRichiestaAttrezzatura(
                viaggio_id=viaggio.id,
                tappa_id=tappa.id,
                tipo_attrezzatura=tipo_clean,
                quantita=q,
            )
        )

    db.commit()
    return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)


@router.get(
    "/manager/trasporti/viaggi/{viaggio_id}/modifica",
    response_class=HTMLResponse,
    name="manager_trasporti_viaggi_edit",
)
def manager_trasporti_viaggi_edit(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    autisti, mezzi, luoghi = _load_trip_form_dependencies(db)
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.richieste_attrezzature),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
        )
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    form_data = {
        "codice_viaggio": viaggio.codice_viaggio or "",
        "data_partenza": viaggio.data_partenza.isoformat() if viaggio.data_partenza else "",
        "data_arrivo_prevista": viaggio.data_arrivo_prevista.isoformat() if viaggio.data_arrivo_prevista else "",
        "autista_id": str(viaggio.autista_id or ""),
        "mezzo_id": str(viaggio.mezzo_id or ""),
        "origine_place": _trip_place_value(viaggio, "origine"),
        "destinazione_place": _trip_place_value(viaggio, "destinazione"),
        "tappa_destinazione": [_stop_place_value(tappa) for tappa in viaggio.tappe] or [""],
        "tipo_attrezzatura": [req.tipo_attrezzatura for req in viaggio.richieste_attrezzature] or ["", "", ""],
        "quantita": [str(req.quantita) for req in viaggio.richieste_attrezzature] or ["1", "1", "1"],
        "richiesta_tappa_idx": [
            str(next((tappa.ordine for tappa in viaggio.tappe if tappa.id == req.tappa_id), 1))
            for req in viaggio.richieste_attrezzature
        ] or ["1", "1", "1"],
    }
    while len(form_data["tappa_destinazione"]) < 3:
        form_data["tappa_destinazione"].append("")
    while len(form_data["tipo_attrezzatura"]) < 3:
        form_data["tipo_attrezzatura"].append("")
        form_data["quantita"].append("1")
        form_data["richiesta_tappa_idx"].append("1")

    return render_template(
        templates,
        request,
        "manager/trasporti/new_trip.html",
        {
            "autisti": autisti,
            "mezzi": mezzi,
            "locations": luoghi,
            "mode": "edit",
            "viaggio": viaggio,
            "form_action": request.url_for("manager_trasporti_viaggi_update", viaggio_id=viaggio.id),
            "form_data": form_data,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/trasporti/viaggi/{viaggio_id}/modifica",
    response_class=HTMLResponse,
    name="manager_trasporti_viaggi_update",
)
def manager_trasporti_viaggi_update(
    viaggio_id: int,
    request: Request,
    codice_viaggio: str = Form(...),
    data_partenza: str = Form(...),
    data_arrivo_prevista: str | None = Form(None),
    autista_id: int | None = Form(None),
    mezzo_id: int | None = Form(None),
    origine_place: str = Form(...),
    destinazione_place: str = Form(...),
    tappa_destinazione: list[str] = Form(default=[]),
    tipo_attrezzatura: list[str] = Form(default=[]),
    quantita: list[str] = Form(default=[]),
    richiesta_tappa_idx: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    autisti, mezzi, luoghi = _load_trip_form_dependencies(db)
    viaggio = (
        db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.richieste_attrezzature), joinedload(TrasportoViaggio.tappe))
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    form_data = {
        "codice_viaggio": codice_viaggio,
        "data_partenza": data_partenza,
        "data_arrivo_prevista": data_arrivo_prevista or "",
        "autista_id": str(autista_id or ""),
        "mezzo_id": str(mezzo_id or ""),
        "origine_place": origine_place,
        "destinazione_place": destinazione_place,
        "tappa_destinazione": tappa_destinazione,
        "tipo_attrezzatura": tipo_attrezzatura,
        "quantita": quantita,
        "richiesta_tappa_idx": richiesta_tappa_idx,
    }
    origine_obj = get_place_by_value(db, origine_place, include_inactive=False)
    destinazione_obj = get_place_by_value(db, destinazione_place, include_inactive=False)
    if not origine_obj or not destinazione_obj:
        return render_template(
            templates,
            request,
            "manager/trasporti/new_trip.html",
            {
                "autisti": autisti,
                "mezzi": mezzi,
                "locations": luoghi,
                "mode": "edit",
                "viaggio": viaggio,
                "form_action": request.url_for("manager_trasporti_viaggi_update", viaggio_id=viaggio.id),
                "form_data": form_data,
                "error_message": "Seleziona origine e destinazione da un luogo esistente.",
            },
            db,
            current_user,
            status_code=400,
        )

    viaggio.codice_viaggio = codice_viaggio.strip().upper()
    viaggio.data_partenza = datetime.strptime(data_partenza, "%Y-%m-%d").date()
    viaggio.data_arrivo_prevista = datetime.strptime(data_arrivo_prevista, "%Y-%m-%d").date() if data_arrivo_prevista else None
    viaggio.autista_id = autista_id
    viaggio.mezzo_id = mezzo_id
    _apply_trip_place(viaggio, "origine", origine_obj)
    _apply_trip_place(viaggio, "destinazione", destinazione_obj)

    db.query(TrasportoAttrezzaturaViaggio).filter(TrasportoAttrezzaturaViaggio.viaggio_id == viaggio.id).delete()
    db.query(TrasportoRichiestaAttrezzatura).filter(TrasportoRichiestaAttrezzatura.viaggio_id == viaggio.id).delete()
    db.query(TrasportoTappa).filter(TrasportoTappa.viaggio_id == viaggio.id).delete()
    db.flush()

    tappe_clean = [get_place_by_value(db, raw, include_inactive=False) for raw in tappa_destinazione if (raw or "").strip()]
    tappe_clean = [tappa for tappa in tappe_clean if tappa is not None]
    if not tappe_clean:
        tappe_clean = [destinazione_obj]

    tappe: list[TrasportoTappa] = []
    for idx, place in enumerate(tappe_clean, start=1):
        tappa = TrasportoTappa(
            viaggio_id=viaggio.id,
            ordine=idx,
            destinazione=place.name,
            site_id=place.id if place.kind == "site" else None,
            depot_id=place.id if place.kind == "depot" else None,
        )
        db.add(tappa)
        tappe.append(tappa)
    db.flush()

    for idx, tipo in enumerate(tipo_attrezzatura):
        tipo_clean = (tipo or "").strip().lower()
        if not tipo_clean:
            continue
        q_raw = quantita[idx] if idx < len(quantita) else "1"
        q = max(1, int(q_raw or 1))
        tappa_idx_raw = richiesta_tappa_idx[idx] if idx < len(richiesta_tappa_idx) else "1"
        tappa_idx = max(1, int(tappa_idx_raw or 1))
        tappa = tappe[tappa_idx - 1] if tappa_idx <= len(tappe) else tappe[-1]
        db.add(
            TrasportoRichiestaAttrezzatura(
                viaggio_id=viaggio.id,
                tappa_id=tappa.id,
                tipo_attrezzatura=tipo_clean,
                quantita=q,
            )
        )

    db.commit()
    return RedirectResponse(url=request.url_for("manager_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


@router.get("/manager/trasporti/viaggi/{viaggio_id}", response_class=HTMLResponse, name="manager_trasporti_viaggi_detail")
def manager_trasporti_viaggi_detail(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    autisti = db.query(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).filter(Role.name == RoleEnum.driver, User.is_active.is_(True)).distinct().order_by(User.full_name, User.email).all()
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.autista),
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)
    _decorate_trip_locations(viaggio)

    assigned_counts: dict[str, list[str]] = {}
    for ass in viaggio.assegnazioni_attrezzature:
        key = (ass.attrezzatura.tipo or "").strip().lower()
        assigned_counts.setdefault(key, []).append(ass.attrezzatura.codice)

    equipment_panel = []
    richieste_disponibili = []
    for req in viaggio.richieste_attrezzature:
        key = (req.tipo_attrezzatura or "").strip().lower()
        codes = assigned_counts.get(key, [])
        disponibili = (
            db.query(Attrezzatura)
            .filter(Attrezzatura.tipo == req.tipo_attrezzatura, Attrezzatura.stato == AttrezzaturaStatoEnum.disponibile)
            .order_by(Attrezzatura.codice.asc())
            .all()
        )
        richieste_disponibili.append((req, disponibili))
        for idx in range(req.quantita):
            selected_code = codes[idx] if idx < len(codes) else None
            equipment_panel.append(
                {
                    "tipo": req.tipo_attrezzatura,
                    "selected_code": selected_code,
                    "ok": bool(selected_code),
                }
            )

    return render_template(
        templates,
        request,
        "manager/trasporti/trip_detail.html",
        {
            "viaggio": viaggio,
            "autisti": autisti,
            "equipment_panel": equipment_panel,
            "richieste_disponibili": richieste_disponibili,
            "can_manage_trip": can_access_manager_area(current_user),
            "can_prepare_trip_load": can_manage_trip_loads(current_user),
        },
        db,
        current_user,
    )


@router.post("/manager/trasporti/viaggi/{viaggio_id}/autista", response_class=HTMLResponse, name="manager_trasporti_viaggi_autista_update")
def manager_trasporti_viaggi_autista_update(
    viaggio_id: int,
    request: Request,
    autista_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id).first()
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    if autista_id is None:
        viaggio.autista_id = None
    else:
        autista = db.query(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).filter(User.id == autista_id, Role.name == RoleEnum.driver, User.is_active.is_(True)).distinct().first()
        if not autista:
            raise HTTPException(status_code=400, detail="Autista non valido")
        viaggio.autista_id = autista.id

    db.commit()
    return RedirectResponse(url=request.url_for("manager_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


@router.get("/driver/trasporti/viaggi", response_class=HTMLResponse, name="driver_trasporti_viaggi")
def driver_trasporti_viaggi(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    viaggi_assegnati = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
        )
        .filter(TrasportoViaggio.autista_id == current_user.id)
        .order_by(TrasportoViaggio.data_partenza.desc())
        .all()
    )

    viaggi_disponibili = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
        )
        .filter(TrasportoViaggio.autista_id.is_(None))
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
    viaggi_assegnati = [_decorate_trip_locations(viaggio) for viaggio in viaggi_assegnati]
    viaggi_disponibili = [_decorate_trip_locations(viaggio) for viaggio in viaggi_disponibili]
    return render_template(
        templates,
        request,
        "driver/trasporti/assigned_trips.html",
        {"viaggi_assegnati": viaggi_assegnati, "viaggi_disponibili": viaggi_disponibili},
        db,
        current_user,
    )


@router.get("/driver/trasporti/oggi", response_class=HTMLResponse, name="driver_trasporti_oggi")
def driver_trasporti_oggi(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    today = date.today()
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(TrasportoViaggio.autista_id == current_user.id, TrasportoViaggio.data_partenza == today)
        .order_by(TrasportoViaggio.id.desc())
        .first()
    )
    richieste = []
    if viaggio:
        _decorate_trip_locations(viaggio)
        for req in viaggio.richieste_attrezzature:
            disponibili = (
                db.query(Attrezzatura)
                .filter(Attrezzatura.tipo == req.tipo_attrezzatura, Attrezzatura.stato == AttrezzaturaStatoEnum.disponibile)
                .order_by(Attrezzatura.codice.asc())
                .all()
            )
            richieste.append((req, disponibili))

    return render_template(
        templates,
        request,
        "driver/trasporti/oggi.html",
        {"viaggio": viaggio, "richieste_disponibili": richieste},
        db,
        current_user,
    )


@router.post("/driver/trasporti/viaggi/{viaggio_id}/prendi", response_class=HTMLResponse, name="driver_trasporti_viaggi_prendi")
def driver_trasporti_viaggi_prendi(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)

    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id).first()
    if not viaggio:
        return RedirectResponse(url=request.url_for("driver_trasporti_viaggi"), status_code=303)

    if viaggio.autista_id is None:
        viaggio.autista_id = current_user.id
        db.commit()

    return RedirectResponse(url=request.url_for("driver_trasporti_viaggi"), status_code=303)


@router.get("/driver/trasporti/viaggi/{viaggio_id}", response_class=HTMLResponse, name="driver_trasporti_viaggi_detail")
def driver_trasporti_viaggi_detail(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(
            TrasportoViaggio.id == viaggio_id,
            func.coalesce(TrasportoViaggio.autista_id, current_user.id) == current_user.id,
        )
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("driver_trasporti_viaggi"), status_code=303)
    _decorate_trip_locations(viaggio)

    richieste = []
    for req in viaggio.richieste_attrezzature:
        disponibili = (
            db.query(Attrezzatura)
            .filter(Attrezzatura.tipo == req.tipo_attrezzatura, Attrezzatura.stato == AttrezzaturaStatoEnum.disponibile)
            .order_by(Attrezzatura.codice.asc())
            .all()
        )
        richieste.append((req, disponibili))

    return render_template(
        templates,
        request,
        "driver/trasporti/trip_detail.html",
        {"viaggio": viaggio, "richieste_disponibili": richieste},
        db,
        current_user,
    )


@router.post("/manager/trasporti/viaggi/{viaggio_id}/carico", response_class=HTMLResponse, name="manager_trasporti_viaggi_carico")
async def manager_trasporti_viaggi_carico(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_trip_load_operator(current_user)
    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id).first()
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    db.query(TrasportoAttrezzaturaViaggio).filter(TrasportoAttrezzaturaViaggio.viaggio_id == viaggio.id).delete()

    form = await request.form()
    richieste = db.query(TrasportoRichiestaAttrezzatura).filter(TrasportoRichiestaAttrezzatura.viaggio_id == viaggio.id).all()
    for req in richieste:
        for idx in range(req.quantita):
            field_name = f"req_{req.id}_{idx}"
            raw_attrezzatura_id = form.get(field_name)
            if not raw_attrezzatura_id:
                continue
            attrezzatura = (
                db.query(Attrezzatura)
                .filter(
                    Attrezzatura.id == int(raw_attrezzatura_id),
                    Attrezzatura.tipo == req.tipo_attrezzatura,
                    Attrezzatura.stato == AttrezzaturaStatoEnum.disponibile,
                )
                .first()
            )
            if attrezzatura:
                attrezzatura.stato = AttrezzaturaStatoEnum.in_trasporto
                db.add(TrasportoAttrezzaturaViaggio(
                    viaggio_id=viaggio.id,
                    attrezzatura_id=attrezzatura.id,
                    tappa_destinazione_id=req.tappa_id,
                    caricato=True,
                ))

    viaggio.stato = TrasportoStatoEnum.in_carico
    db.commit()
    return RedirectResponse(url=request.url_for("manager_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


@router.post("/driver/trasporti/viaggi/{viaggio_id}/carico", response_class=HTMLResponse, name="driver_trasporti_viaggi_carico")
async def driver_trasporti_viaggi_carico(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id, TrasportoViaggio.autista_id == current_user.id).first()
    if not viaggio:
        return RedirectResponse(url=request.url_for("driver_trasporti_viaggi"), status_code=303)

    db.query(TrasportoAttrezzaturaViaggio).filter(TrasportoAttrezzaturaViaggio.viaggio_id == viaggio.id).delete()

    form = await request.form()
    richieste = db.query(TrasportoRichiestaAttrezzatura).filter(TrasportoRichiestaAttrezzatura.viaggio_id == viaggio.id).all()
    for req in richieste:
        for idx in range(req.quantita):
            field_name = f"req_{req.id}_{idx}"
            raw_attrezzatura_id = form.get(field_name)
            if not raw_attrezzatura_id:
                continue
            attrezzatura = (
                db.query(Attrezzatura)
                .filter(
                    Attrezzatura.id == int(raw_attrezzatura_id),
                    Attrezzatura.tipo == req.tipo_attrezzatura,
                    Attrezzatura.stato == AttrezzaturaStatoEnum.disponibile,
                )
                .first()
            )
            if attrezzatura:
                attrezzatura.stato = AttrezzaturaStatoEnum.in_trasporto
                db.add(TrasportoAttrezzaturaViaggio(
                    viaggio_id=viaggio.id,
                    attrezzatura_id=attrezzatura.id,
                    tappa_destinazione_id=req.tappa_id,
                    caricato=True,
                ))

    viaggio.stato = TrasportoStatoEnum.in_carico
    db.commit()
    return RedirectResponse(url=request.url_for("driver_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


@router.post("/driver/trasporti/viaggi/{viaggio_id}/scan", name="driver_trasporti_viaggi_scan")
def driver_trasporti_viaggi_scan(
    viaggio_id: int,
    qr_code: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    viaggio = db.query(TrasportoViaggio).filter(TrasportoViaggio.id == viaggio_id, TrasportoViaggio.autista_id == current_user.id).first()
    if not viaggio:
        raise HTTPException(status_code=404, detail="Viaggio non trovato")

    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.qr_code == qr_code.strip().upper()).first()
    if not attrezzatura:
        raise HTTPException(status_code=404, detail="Attrezzatura non trovata")

    assignment = db.query(TrasportoAttrezzaturaViaggio).filter(
        TrasportoAttrezzaturaViaggio.viaggio_id == viaggio.id,
        TrasportoAttrezzaturaViaggio.attrezzatura_id == attrezzatura.id,
    ).first()

    action = "none"
    if attrezzatura.stato == AttrezzaturaStatoEnum.disponibile:
        if assignment is None:
            first_tappa = db.query(TrasportoTappa).filter(TrasportoTappa.viaggio_id == viaggio.id).order_by(TrasportoTappa.ordine.asc()).first()
            assignment = TrasportoAttrezzaturaViaggio(
                viaggio_id=viaggio.id,
                attrezzatura_id=attrezzatura.id,
                tappa_destinazione_id=first_tappa.id if first_tappa else None,
            )
            db.add(assignment)
        assignment.caricato = True
        assignment.scaricato = False
        attrezzatura.stato = AttrezzaturaStatoEnum.in_trasporto
        action = "caricato"
    elif assignment and attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto:
        assignment.scaricato = True
        attrezzatura.stato = AttrezzaturaStatoEnum.disponibile
        dest = assignment.tappa_destinazione.destinazione if assignment.tappa_destinazione else viaggio.destinazione
        attrezzatura.posizione_attuale = dest
        action = "scaricato"

    db.commit()
    return {"action": action, "attrezzatura_id": attrezzatura.id, "stato": attrezzatura.stato.value}


@router.post("/driver/trasporti/viaggi/{viaggio_id}/stato", response_class=HTMLResponse, name="driver_trasporti_viaggi_stato")
async def driver_trasporti_viaggi_stato(
    viaggio_id: int,
    request: Request,
    nuovo_stato: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_driver(current_user)
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(TrasportoViaggio.id == viaggio_id, TrasportoViaggio.autista_id == current_user.id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("driver_trasporti_viaggi"), status_code=303)

    stato = TrasportoStatoEnum(nuovo_stato)
    viaggio.stato = stato

    if stato == TrasportoStatoEnum.in_viaggio:
        for ass in viaggio.assegnazioni_attrezzature:
            ass.attrezzatura.stato = AttrezzaturaStatoEnum.in_trasporto

    if stato == TrasportoStatoEnum.completato:
        form = await request.form()
        remaining_ids = {int(v) for v in form.getlist("resta_sul_camion") if str(v).isdigit()}
        now = datetime.utcnow()
        for ass in viaggio.assegnazioni_attrezzature:
            att = ass.attrezzatura
            tappa_dest = ass.tappa_destinazione.destinazione if ass.tappa_destinazione else viaggio.destinazione
            destinazione_site_id = ass.tappa_destinazione.site_id if ass.tappa_destinazione else viaggio.destinazione_site_id
            destinazione_depot_id = ass.tappa_destinazione.depot_id if ass.tappa_destinazione else viaggio.destinazione_depot_id
            if att.id in remaining_ids:
                att.posizione_attuale = "camion"
                ass.scaricato = False
                movement_dest = "camion"
                destinazione_site_id = None
                destinazione_depot_id = None
            else:
                att.posizione_attuale = tappa_dest
                ass.scaricato = True
                movement_dest = tappa_dest
            att.stato = AttrezzaturaStatoEnum.disponibile
            db.add(
                MovimentoAttrezzatura(
                    attrezzatura_id=att.id,
                    viaggio_id=viaggio.id,
                    origine_site_id=viaggio.origine_site_id,
                    origine_depot_id=viaggio.origine_depot_id,
                    destinazione_site_id=destinazione_site_id,
                    destinazione_depot_id=destinazione_depot_id,
                    origine=viaggio.origine,
                    destinazione=movement_dest,
                    data=now,
                    autista_id=current_user.id,
                )
            )

    db.commit()
    return RedirectResponse(url=request.url_for("driver_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


@router.get("/qr/{code}", name="trasporti_qr_lookup")
def trasporti_qr_lookup(
    code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    if not has_perm(current_user, "trasporti.assigned.read") and not can_manage_trip_loads(current_user) and not has_perm(current_user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.qr_code == code.strip().upper()).first()
    if not attrezzatura:
        raise HTTPException(status_code=404, detail="Attrezzatura non trovata")
    return {
        "id": attrezzatura.id,
        "codice": attrezzatura.codice,
        "qr_code": attrezzatura.qr_code,
        "stato": attrezzatura.stato.value,
        "posizione_attuale": attrezzatura.posizione_attuale,
        "tipo": attrezzatura.tipo,
    }


@router.get("/manager/trasporti/movimenti", response_class=HTMLResponse, name="manager_trasporti_movimenti")
def manager_trasporti_movimenti(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    movimenti = (
        db.query(MovimentoAttrezzatura)
        .options(
            joinedload(MovimentoAttrezzatura.attrezzatura),
            joinedload(MovimentoAttrezzatura.viaggio),
            joinedload(MovimentoAttrezzatura.autista),
            joinedload(MovimentoAttrezzatura.origine_site),
            joinedload(MovimentoAttrezzatura.origine_depot),
            joinedload(MovimentoAttrezzatura.destinazione_site),
            joinedload(MovimentoAttrezzatura.destinazione_depot),
        )
        .order_by(MovimentoAttrezzatura.data.desc())
        .limit(200)
        .all()
    )
    for movimento in movimenti:
        movimento.origine_label = _movement_place_label(movimento, "origine")
        movimento.destinazione_label = _movement_place_label(movimento, "destinazione")
    return render_template(templates, request, "manager/trasporti/movimenti.html", {"movimenti": movimenti}, db, current_user)
