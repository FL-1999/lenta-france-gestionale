from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
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
    SiteStatusEnum,
    TrasportoAttrezzaturaViaggio,
    TrasportoRichiestaAttrezzatura,
    TrasportoStatoEnum,
    TrasportoTappa,
    TrasportoViaggio,
    User,
)
from models.veicoli import Veicolo
from services import GPSIntegrationService, get_gps_provider_adapter
from permissions import can_access_logistics_area, can_access_manager_area, can_manage_trip_loads, has_perm
from template_context import register_manager_badges, render_template
from utils.google_maps import estimate_trip_eta
from utils.places import DEFAULT_DEPOT_NAMES
from utils.gps import trip_gps_marker_context
from utils.places import format_place_label, get_place_by_value, get_selectable_places
from utils.trips import can_edit_trip, compute_trip_progress, format_trip_datetime_parts, format_trip_time

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["trasporti"])

WEEKDAY_LABELS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _parse_optional_time(raw_value: str | None) -> time | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def _format_duration_minutes(value: timedelta | None) -> str:
    if not value:
        return "0 min"
    total_minutes = max(int(value.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes} min"
    if hours:
        return f"{hours}h"
    return f"{minutes} min"


def _build_trip_route_summary(viaggio: TrasportoViaggio) -> str:
    route_labels = [viaggio.origine_label]
    route_labels.extend(tappa.destinazione_label for tappa in (viaggio.tappe or []))
    if not route_labels or route_labels[-1] != viaggio.destinazione_label:
        route_labels.append(viaggio.destinazione_label)
    return " → ".join(label for label in route_labels if label and label != "—")


def _sync_trip_eta(viaggio: TrasportoViaggio) -> str:
    if viaggio.arrivo_stimato_manuale:
        viaggio.durata_stimata_minuti = None
        return "Arrivo stimato inserito manualmente"

    viaggio.arrivo_stimato = None
    viaggio.durata_stimata_minuti = None
    route_points = _build_trip_route_points(viaggio)
    eta_result = estimate_trip_eta(viaggio, route_points)
    if eta_result.available:
        viaggio.arrivo_stimato = eta_result.arrival_time
        viaggio.durata_stimata_minuti = eta_result.duration_minutes
    return eta_result.message


def _trip_locked_redirect(request: Request, viaggio_id: int) -> RedirectResponse:
    return RedirectResponse(
        url=f"{request.url_for('manager_trasporti_viaggi_detail', viaggio_id=viaggio_id)}?err=trip_locked",
        status_code=303,
    )


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
    viaggio.can_edit = can_edit_trip(viaggio)
    viaggio.departure_display = format_trip_datetime_parts(viaggio.data_partenza, viaggio.orario_partenza)
    viaggio.arrival_estimate_display = format_trip_time(viaggio.arrivo_stimato)
    viaggio.route_summary = _build_trip_route_summary(viaggio)
    viaggio.arrival_estimate_status = (
        "manuale" if viaggio.arrivo_stimato_manuale and viaggio.arrivo_stimato else "automatico" if viaggio.arrivo_stimato else "non_disponibile"
    )
    progress_data = compute_trip_progress(viaggio)
    viaggio.progress_data = progress_data
    viaggio.progress_percent = progress_data["progress_percent"]
    viaggio.progress_status = progress_data["status"]
    viaggio.progress_status_label = progress_data["status_label"]
    if not progress_data["is_available"]:
        viaggio.progress_timing_text = "Stima non disponibile"
    elif progress_data["status"] == "non_partito":
        viaggio.progress_timing_text = "Non ancora partito"
    elif progress_data["status"] == "in_ritardo":
        viaggio.progress_timing_text = f"In ritardo di {_format_duration_minutes(progress_data['tempo_ritardo'])}"
    else:
        viaggio.progress_timing_text = (
            f"Partito da {_format_duration_minutes(progress_data['tempo_trascorso'])} · "
            f"Arrivo stimato tra {_format_duration_minutes(progress_data['tempo_rimanente'])}"
        )
    return viaggio


def _build_trip_point(
    *,
    name: str | None,
    place_type: str | None,
    role: str,
    lat: float | None,
    lng: float | None,
    site_id: int | None = None,
    depot_id: int | None = None,
) -> dict[str, object]:
    role_labels = {
        "origin": "Origine",
        "stop": "Tappa",
        "destination": "Destinazione",
    }
    type_labels = {
        "site": "Cantiere",
        "depot": "Deposito",
        None: "Luogo",
    }
    return {
        "name": name or "—",
        "type": place_type or "unknown",
        "type_label": type_labels.get(place_type, "Luogo"),
        "role": role,
        "role_label": role_labels.get(role, "Tappa"),
        "lat": lat,
        "lng": lng,
        "site_id": site_id,
        "depot_id": depot_id,
    }


def _trip_point_from_place(site: Site | None, depot: Depot | None, *, role: str, fallback_name: str | None) -> dict[str, object]:
    if site:
        return _build_trip_point(name=site.name, place_type="site", role=role, lat=site.lat, lng=site.lng, site_id=site.id)
    if depot:
        return _build_trip_point(name=depot.name, place_type="depot", role=role, lat=depot.lat, lng=depot.lng, depot_id=depot.id)
    return _build_trip_point(name=fallback_name, place_type=None, role=role, lat=None, lng=None)


def _stop_trip_point(tappa: TrasportoTappa) -> dict[str, object]:
    if tappa.site:
        return _build_trip_point(name=tappa.site.name, place_type="site", role="stop", lat=tappa.site.lat, lng=tappa.site.lng, site_id=tappa.site.id)
    if tappa.depot:
        return _build_trip_point(name=tappa.depot.name, place_type="depot", role="stop", lat=tappa.depot.lat, lng=tappa.depot.lng, depot_id=tappa.depot.id)
    return _build_trip_point(name=tappa.destinazione, place_type=None, role="stop", lat=None, lng=None)


def _build_trip_route_points(viaggio: TrasportoViaggio) -> list[dict[str, object]]:
    destination_key = _trip_place_value(viaggio, "destinazione")
    filtered_stops: list[TrasportoTappa] = []
    for tappa in viaggio.tappe or []:
        current_key = _stop_place_value(tappa)
        is_duplicate_destination = bool(destination_key and current_key and current_key == destination_key and tappa.ordine == max((stop.ordine for stop in viaggio.tappe), default=tappa.ordine))
        if is_duplicate_destination:
            continue
        filtered_stops.append(tappa)
    points = [
        _trip_point_from_place(viaggio.origine_site, viaggio.origine_depot, role="origin", fallback_name=viaggio.origine),
        *[_stop_trip_point(tappa) for tappa in filtered_stops],
        _trip_point_from_place(viaggio.destinazione_site, viaggio.destinazione_depot, role="destination", fallback_name=viaggio.destinazione),
    ]
    for index, point in enumerate(points, start=1):
        point["sequence"] = index
    return points


def _trip_has_any_coordinates(points: list[dict[str, object]]) -> bool:
    return any(point.get("lat") is not None and point.get("lng") is not None for point in points)


def _trip_has_mappable_route(points: list[dict[str, object]]) -> bool:
    return sum(1 for point in points if point.get("lat") is not None and point.get("lng") is not None) >= 2


def _google_maps_location_value(point: dict[str, object]) -> str | None:
    lat = point.get("lat")
    lng = point.get("lng")
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    name = str(point.get("name") or "").strip()
    return name or None


def _build_trip_google_maps_url(points: list[dict[str, object]]) -> str | None:
    if len(points) < 2:
        return None
    origin = _google_maps_location_value(points[0])
    destination = _google_maps_location_value(points[-1])
    if not origin or not destination:
        return None

    params: list[tuple[str, str]] = [
        ("api", "1"),
        ("travelmode", "driving"),
        ("origin", origin),
        ("destination", destination),
    ]
    waypoints = [
        value
        for value in (_google_maps_location_value(point) for point in points[1:-1])
        if value
    ]
    if waypoints:
        params.append(("waypoints", "|".join(waypoints)))
    return f"https://www.google.com/maps/dir/?{urlencode(params, quote_via=quote, safe='|,')}"


def _build_trip_map_context(viaggio: TrasportoViaggio) -> dict[str, object]:
    points = _build_trip_route_points(viaggio)
    return {
        "trip_route_points": points,
        "trip_has_any_coordinates": _trip_has_any_coordinates(points),
        "trip_has_mappable_route": _trip_has_mappable_route(points),
        "trip_google_maps_url": _build_trip_google_maps_url(points),
    }




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
    viaggi = [_decorate_trip_locations(trip) for trip in viaggi]
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
        if not can_edit_trip(viaggio):
            return _trip_locked_redirect(request, viaggio.id)
        viaggio.data_partenza = datetime.strptime(target_date, "%Y-%m-%d").date()
        _sync_trip_eta(viaggio)
        db.commit()
    redirect_week = request.query_params.get("week_start") or target_date
    return RedirectResponse(url=f"{request.url_for('manager_trasporti_planner')}?week_start={redirect_week}", status_code=303)


@router.post("/manager/trasporti/gps/sync", name="manager_trasporti_gps_sync")
def manager_trasporti_gps_sync(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    _ensure_manager(current_user)

    provider = get_gps_provider_adapter()
    service = GPSIntegrationService(provider)
    sync_result = service.sync_truck_positions(db)
    query = urlencode(
        {
            "gps_sync": "ok",
            "gps_updated": sync_result.get("updated", 0),
            "gps_trucks": sync_result.get("trucks", 0),
        }
    )
    return RedirectResponse(url=f"{request.url_for('manager_trasporti_mappa')}?{query}", status_code=303)


@router.post("/api/trasporti/gps/webhook", name="api_trasporti_gps_webhook")
def api_trasporti_gps_webhook(
    payload: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
):
    provider = get_gps_provider_adapter()
    service = GPSIntegrationService(provider)
    result = service.ingest_webhook_positions(db, payload)
    return result


@router.get("/manager/trasporti/mappa", response_class=HTMLResponse, name="manager_trasporti_mappa")
def manager_trasporti_mappa(
    request: Request,
    view: str = "generale",
    date_from: str | None = None,
    date_to: str | None = None,
    stato_viaggio: str = "all",
    cantiere_id: int | None = None,
    mezzo_id: int | None = None,
    autista_id: int | None = None,
    gps_sync: str | None = None,
    gps_updated: int | None = None,
    gps_trucks: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_logistics_access(current_user)
    _ensure_manager(current_user)

    sites = db.query(Site).order_by(Site.name.asc()).all()
    depots = db.query(Depot).filter(func.lower(func.trim(Depot.name)).notin_(DEFAULT_DEPOT_NAMES)).order_by(Depot.name.asc()).all()

    trip_query = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.autista),
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.origine_site),
            joinedload(TrasportoViaggio.origine_depot),
            joinedload(TrasportoViaggio.destinazione_site),
            joinedload(TrasportoViaggio.destinazione_depot),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.site),
            joinedload(TrasportoViaggio.tappe).joinedload(TrasportoTappa.depot),
        )
        .order_by(TrasportoViaggio.data_partenza.desc(), TrasportoViaggio.id.desc())
    )

    if date_from:
        try:
            trip_query = trip_query.filter(TrasportoViaggio.data_partenza >= datetime.strptime(date_from, "%Y-%m-%d").date())
        except ValueError:
            date_from = None
    if date_to:
        try:
            trip_query = trip_query.filter(TrasportoViaggio.data_partenza <= datetime.strptime(date_to, "%Y-%m-%d").date())
        except ValueError:
            date_to = None

    if stato_viaggio != "all":
        allowed_states = {state.value for state in TrasportoStatoEnum}
        if stato_viaggio in allowed_states:
            trip_query = trip_query.filter(TrasportoViaggio.stato == TrasportoStatoEnum(stato_viaggio))
        else:
            stato_viaggio = "all"

    if mezzo_id:
        trip_query = trip_query.filter(TrasportoViaggio.mezzo_id == mezzo_id)
    if autista_id:
        trip_query = trip_query.filter(TrasportoViaggio.autista_id == autista_id)
    if cantiere_id:
        trip_query = trip_query.filter(
            (TrasportoViaggio.origine_site_id == cantiere_id)
            | (TrasportoViaggio.destinazione_site_id == cantiere_id)
            | (TrasportoViaggio.tappe.any(TrasportoTappa.site_id == cantiere_id))
        )

    trips = trip_query.all()

    map_sites = []
    skipped_sites = 0
    for site in sites:
        if site.lat is None or site.lng is None:
            skipped_sites += 1
            continue
        map_sites.append(
            {
                "id": site.id,
                "name": site.name,
                "city": site.city,
                "status": site.status.value if site.status else None,
                "status_label": "Attivo" if site.status == SiteStatusEnum.aperto else "Chiuso",
                "lat": float(site.lat),
                "lng": float(site.lng),
                "detail_url": str(request.url_for("manager_site_detail", site_id=site.id)),
            }
        )

    map_depots = []
    skipped_depots = 0
    for depot in depots:
        if depot.lat is None or depot.lng is None:
            skipped_depots += 1
            continue
        map_depots.append(
            {
                "id": depot.id,
                "name": depot.name,
                "city": depot.city,
                "is_active": bool(depot.is_active),
                "lat": float(depot.lat),
                "lng": float(depot.lng),
                "detail_url": str(request.url_for("manager_depositi_edit", depot_id=depot.id)),
            }
        )

    trip_state_labels = {
        TrasportoStatoEnum.programmato.value: "Programmato",
        TrasportoStatoEnum.in_carico.value: "In carico",
        TrasportoStatoEnum.in_viaggio.value: "In viaggio",
        TrasportoStatoEnum.arrivato.value: "Arrivato",
        TrasportoStatoEnum.completato.value: "Completato",
    }

    map_trips = []
    skipped_trip_points = 0
    trips_with_real_gps = 0
    trips_with_gps_fallback = 0
    for trip in trips:
        _decorate_trip_locations(trip)
        route_points = _build_trip_route_points(trip)
        points_with_coords = [point for point in route_points if point.get("lat") is not None and point.get("lng") is not None]
        gps_context = trip_gps_marker_context(trip)
        if not points_with_coords and not gps_context.get("gps_available"):
            skipped_trip_points += 1
            continue

        center_point = points_with_coords[min(len(points_with_coords) // 2, len(points_with_coords) - 1)] if points_with_coords else None
        marker_lat = float(gps_context["lat"]) if gps_context.get("gps_available") else float(center_point["lat"])
        marker_lng = float(gps_context["lng"]) if gps_context.get("gps_available") else float(center_point["lng"])
        autista_name = None
        if trip.autista:
            autista_name = trip.autista.full_name or trip.autista.email

        mezzo_label = None
        if trip.mezzo:
            mezzo_label = f"{(trip.mezzo.marca or '').strip()} {(trip.mezzo.modello or '').strip()} ({trip.mezzo.targa})".strip()

        if gps_context.get("source") == "gps_reale":
            trips_with_real_gps += 1
        elif (trip.mezzo and (trip.mezzo.categoria or "").strip().lower() == "camion"):
            trips_with_gps_fallback += 1

        map_trips.append(
            {
                "id": trip.id,
                "code": trip.codice_viaggio,
                "state": trip.stato.value,
                "state_label": trip_state_labels.get(trip.stato.value, trip.stato.value),
                "date": trip.data_partenza.isoformat() if trip.data_partenza else None,
                "origin": trip.origine_label,
                "destination": trip.destinazione_label,
                "driver_id": trip.autista_id,
                "driver_name": autista_name,
                "vehicle_id": trip.mezzo_id,
                "vehicle_label": mezzo_label,
                "marker": {
                    "lat": marker_lat,
                    "lng": marker_lng,
                },
                "marker_source": gps_context.get("source", "stimata"),
                "gps": gps_context,
                "route_points": points_with_coords,
                "has_full_route": len(points_with_coords) == len(route_points),
                "detail_url": str(request.url_for("manager_trasporti_viaggi_detail", viaggio_id=trip.id)),
            }
        )

    available_drivers = sorted(
        [
            {"id": trip.autista_id, "label": (trip.autista.full_name or trip.autista.email) if trip.autista else f"ID {trip.autista_id}"}
            for trip in trips
            if trip.autista_id
        ],
        key=lambda item: item["label"].lower(),
    )
    unique_drivers = []
    seen_driver_ids = set()
    for item in available_drivers:
        if item["id"] in seen_driver_ids:
            continue
        seen_driver_ids.add(item["id"])
        unique_drivers.append(item)

    available_vehicles = sorted(
        [
            {
                "id": trip.mezzo_id,
                "label": (
                    f"{(trip.mezzo.marca or '').strip()} {(trip.mezzo.modello or '').strip()} ({trip.mezzo.targa})".strip()
                    if trip.mezzo
                    else f"Mezzo {trip.mezzo_id}"
                ),
            }
            for trip in trips
            if trip.mezzo_id
        ],
        key=lambda item: item["label"].lower(),
    )
    unique_vehicles = []
    seen_vehicle_ids = set()
    for item in available_vehicles:
        if item["id"] in seen_vehicle_ids:
            continue
        seen_vehicle_ids.add(item["id"])
        unique_vehicles.append(item)

    selected_view = view if view in {"generale", "trasporti", "cantieri_attivi", "cantieri_chiusi", "depositi", "mezzi", "autisti"} else "generale"

    map_payload = {
        "sites": map_sites,
        "depots": map_depots,
        "trips": map_trips,
        "filters": {
            "selected_view": selected_view,
            "selected": {
                "stato_viaggio": stato_viaggio,
                "date_from": date_from,
                "date_to": date_to,
                "cantiere_id": cantiere_id,
                "mezzo_id": mezzo_id,
                "autista_id": autista_id,
            },
            "drivers": unique_drivers,
            "vehicles": unique_vehicles,
            "sites": [{"id": site.id, "name": site.name} for site in sites],
            "trip_states": [{"value": "all", "label": "Tutti"}] + [
                {"value": state.value, "label": trip_state_labels[state.value]} for state in TrasportoStatoEnum
            ],
        },
        "stats": {
            "sites_missing_coordinates": skipped_sites,
            "depots_missing_coordinates": skipped_depots,
            "trips_missing_coordinates": skipped_trip_points,
            "trips_with_real_gps": trips_with_real_gps,
            "trips_with_gps_fallback": trips_with_gps_fallback,
        },
        "gps_sync": {
            "status": gps_sync,
            "updated": gps_updated,
            "trucks": gps_trucks,
        },
    }

    return render_template(
        templates,
        request,
        "manager/trasporti/mappa.html",
        {"map_payload": map_payload},
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
                "orario_partenza": "",
                "data_arrivo_prevista": "",
                "arrivo_stimato_manuale": "",
                "autista_id": "",
                "mezzo_id": "",
                "origine_place": "",
                "destinazione_place": "",
                "materiali_attrezzature": "",
                "note": "",
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
    orario_partenza: str | None = Form(None),
    data_arrivo_prevista: str | None = Form(None),
    arrivo_stimato_manuale: str | None = Form(None),
    autista_id: int | None = Form(None),
    mezzo_id: int | None = Form(None),
    origine_place: str = Form(...),
    destinazione_place: str = Form(...),
    materiali_attrezzature: str | None = Form(None),
    note: str | None = Form(None),
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
        "orario_partenza": orario_partenza or "",
        "data_arrivo_prevista": data_arrivo_prevista or "",
        "arrivo_stimato_manuale": arrivo_stimato_manuale or "",
        "autista_id": str(autista_id or ""),
        "mezzo_id": str(mezzo_id or ""),
        "origine_place": origine_place,
        "destinazione_place": destinazione_place,
        "materiali_attrezzature": materiali_attrezzature or "",
        "note": note or "",
        "tappa_destinazione": tappa_destinazione,
        "tipo_attrezzatura": tipo_attrezzatura,
        "quantita": quantita,
        "richiesta_tappa_idx": richiesta_tappa_idx,
    }
    try:
        parsed_orario_partenza = _parse_optional_time(orario_partenza)
        parsed_arrivo_manuale = _parse_optional_time(arrivo_stimato_manuale)
    except ValueError:
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
                "error_message": "Formato orario non valido. Usa HH:MM.",
            },
            db,
            current_user,
            status_code=400,
        )
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
        orario_partenza=parsed_orario_partenza,
        data_arrivo_prevista=datetime.strptime(data_arrivo_prevista, "%Y-%m-%d").date() if data_arrivo_prevista else None,
        arrivo_stimato=parsed_arrivo_manuale,
        arrivo_stimato_manuale=parsed_arrivo_manuale is not None,
        autista_id=autista_id,
        mezzo_id=mezzo_id,
        origine=origine_obj.name,
        destinazione=destinazione_obj.name,
        materiali_attrezzature=(materiali_attrezzature or "").strip() or None,
        note=(note or "").strip() or None,
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

    eta_message = _sync_trip_eta(viaggio)
    db.commit()
    return RedirectResponse(url=f"{request.url_for('manager_trasporti_dashboard')}?msg={quote(eta_message)}", status_code=303)


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
    if not can_edit_trip(viaggio):
        return _trip_locked_redirect(request, viaggio.id)

    form_data = {
        "codice_viaggio": viaggio.codice_viaggio or "",
        "data_partenza": viaggio.data_partenza.isoformat() if viaggio.data_partenza else "",
        "orario_partenza": viaggio.orario_partenza.strftime("%H:%M") if viaggio.orario_partenza else "",
        "data_arrivo_prevista": viaggio.data_arrivo_prevista.isoformat() if viaggio.data_arrivo_prevista else "",
        "arrivo_stimato_manuale": viaggio.arrivo_stimato.strftime("%H:%M") if viaggio.arrivo_stimato and viaggio.arrivo_stimato_manuale else "",
        "autista_id": str(viaggio.autista_id or ""),
        "mezzo_id": str(viaggio.mezzo_id or ""),
        "origine_place": _trip_place_value(viaggio, "origine"),
        "destinazione_place": _trip_place_value(viaggio, "destinazione"),
        "materiali_attrezzature": viaggio.materiali_attrezzature or "",
        "note": viaggio.note or "",
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
            "eta_message": "Arrivo stimato inserito manualmente" if viaggio.arrivo_stimato_manuale and viaggio.arrivo_stimato else ("Arrivo stimato calcolato automaticamente" if viaggio.arrivo_stimato else "Arrivo stimato non disponibile"),
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
    orario_partenza: str | None = Form(None),
    data_arrivo_prevista: str | None = Form(None),
    arrivo_stimato_manuale: str | None = Form(None),
    autista_id: int | None = Form(None),
    mezzo_id: int | None = Form(None),
    origine_place: str = Form(...),
    destinazione_place: str = Form(...),
    materiali_attrezzature: str | None = Form(None),
    note: str | None = Form(None),
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
    if not can_edit_trip(viaggio):
        return _trip_locked_redirect(request, viaggio.id)

    form_data = {
        "codice_viaggio": codice_viaggio,
        "data_partenza": data_partenza,
        "orario_partenza": orario_partenza or "",
        "data_arrivo_prevista": data_arrivo_prevista or "",
        "arrivo_stimato_manuale": arrivo_stimato_manuale or "",
        "autista_id": str(autista_id or ""),
        "mezzo_id": str(mezzo_id or ""),
        "origine_place": origine_place,
        "destinazione_place": destinazione_place,
        "materiali_attrezzature": materiali_attrezzature or "",
        "note": note or "",
        "tappa_destinazione": tappa_destinazione,
        "tipo_attrezzatura": tipo_attrezzatura,
        "quantita": quantita,
        "richiesta_tappa_idx": richiesta_tappa_idx,
    }
    try:
        parsed_orario_partenza = _parse_optional_time(orario_partenza)
        parsed_arrivo_manuale = _parse_optional_time(arrivo_stimato_manuale)
    except ValueError:
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
                "error_message": "Formato orario non valido. Usa HH:MM.",
            },
            db,
            current_user,
            status_code=400,
        )
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
    viaggio.orario_partenza = parsed_orario_partenza
    viaggio.data_arrivo_prevista = datetime.strptime(data_arrivo_prevista, "%Y-%m-%d").date() if data_arrivo_prevista else None
    viaggio.arrivo_stimato = parsed_arrivo_manuale
    viaggio.arrivo_stimato_manuale = parsed_arrivo_manuale is not None
    viaggio.autista_id = autista_id
    viaggio.mezzo_id = mezzo_id
    viaggio.materiali_attrezzature = (materiali_attrezzature or "").strip() or None
    viaggio.note = (note or "").strip() or None
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

    eta_message = _sync_trip_eta(viaggio)
    db.commit()
    return RedirectResponse(
        url=f"{request.url_for('manager_trasporti_viaggi_detail', viaggio_id=viaggio.id)}?msg={quote(eta_message)}",
        status_code=303,
    )


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
            "trip_editable": can_edit_trip(viaggio),
            "can_prepare_trip_load": can_manage_trip_loads(current_user),
            "trip_eta_message": request.query_params.get("msg") or ("Arrivo stimato inserito manualmente" if viaggio.arrivo_stimato_manuale and viaggio.arrivo_stimato else ("Arrivo stimato calcolato automaticamente" if viaggio.arrivo_stimato else "Arrivo stimato non disponibile")),
            "trip_error": request.query_params.get("err"),
            **_build_trip_map_context(viaggio),
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
    if not can_edit_trip(viaggio):
        return _trip_locked_redirect(request, viaggio.id)

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
        {"viaggio": viaggio, "richieste_disponibili": richieste, **(_build_trip_map_context(viaggio) if viaggio else {})},
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
        {
            "viaggio": viaggio,
            "richieste_disponibili": richieste,
            **_build_trip_map_context(viaggio),
        },
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

    def _resp(action: str, reason: str | None = None):
        return {
            "action": action,
            "reason": reason,
            "attrezzatura_id": attrezzatura.id,
            "codice": attrezzatura.codice,
            "nome": getattr(attrezzatura, "nome", None) or attrezzatura.codice,
            "stato": attrezzatura.stato.value if attrezzatura.stato else None,
        }

    # Scarico: già a bordo di QUESTO viaggio → si può sempre scaricare.
    if assignment and attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto:
        assignment.scaricato = True
        attrezzatura.stato = AttrezzaturaStatoEnum.disponibile
        dest = assignment.tappa_destinazione.destinazione if assignment.tappa_destinazione else viaggio.destinazione
        attrezzatura.posizione_attuale = dest
        db.commit()
        return _resp("scaricato")

    # Carico: consentito SOLO se l'attrezzatura è disponibile.
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
        db.commit()
        return _resp("caricato")

    # Bloccata: stato non compatibile con il carico. Nessuna modifica.
    if attrezzatura.stato == AttrezzaturaStatoEnum.manutenzione:
        reason = "manutenzione"
    elif attrezzatura.stato == AttrezzaturaStatoEnum.in_uso:
        reason = "in_uso"
    elif attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto:
        # in trasporto ma NON assegnata a questo viaggio → è su un altro mezzo/viaggio
        reason = "altro_viaggio"
    else:
        reason = "non_disponibile"
    return _resp("bloccato", reason)


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
