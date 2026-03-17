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
    MovimentoAttrezzatura,
    RoleEnum,
    Site,
    TrasportoAttrezzaturaViaggio,
    TrasportoRichiestaAttrezzatura,
    TrasportoStatoEnum,
    TrasportoTappa,
    TrasportoViaggio,
    User,
)
from models.veicoli import Veicolo
from permissions import has_perm
from template_context import register_manager_badges, render_template

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["trasporti"])

WEEKDAY_LABELS = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_driver(user: User) -> None:
    if not has_perm(user, "trasporti.assigned.read"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli autisti")


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
    _ensure_manager(current_user)
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
        joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
        joinedload(TrasportoViaggio.tappe),
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
    autisti = db.query(User).filter(User.role == RoleEnum.driver).order_by(User.full_name, User.email).all()
    mezzi = db.query(Veicolo).filter(Veicolo.visibile_trasporti.is_(True)).order_by(Veicolo.marca, Veicolo.modello).all()
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
    _ensure_manager(current_user)
    sites = (
        db.query(Site)
        .filter(Site.lat.isnot(None), Site.lng.isnot(None), Site.is_active.is_(True))
        .order_by(Site.name.asc())
        .all()
    )
    site_map = {s.name.strip().lower(): s for s in sites if s.name}

    trucks_in_travel = (
        db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.mezzo), joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura))
        .filter(TrasportoViaggio.stato == TrasportoStatoEnum.in_viaggio)
        .all()
    )

    truck_markers = []
    equipment_markers = []
    for trip in trucks_in_travel:
        origin_site = site_map.get((trip.origine or "").strip().lower())
        dest_site = site_map.get((trip.destinazione or "").strip().lower())
        if origin_site and dest_site:
            lat = (origin_site.lat + dest_site.lat) / 2
            lng = (origin_site.lng + dest_site.lng) / 2
        elif dest_site:
            lat, lng = dest_site.lat, dest_site.lng
        elif origin_site:
            lat, lng = origin_site.lat, origin_site.lng
        else:
            continue
        truck_markers.append(
            {
                "lat": float(lat),
                "lng": float(lng),
                "label": f"{trip.codice_viaggio} - {(trip.mezzo.targa if trip.mezzo else 'Senza mezzo')}",
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
            "label": s.name,
            "detail_url": str(request.url_for("manager_site_detail", site_id=s.id)),
        }
        for s in sites
    ]

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
    _ensure_manager(current_user)
    assignments = (
        db.query(TrasportoAttrezzaturaViaggio)
        .options(
            joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoAttrezzaturaViaggio.viaggio).joinedload(TrasportoViaggio.autista),
        )
        .join(TrasportoAttrezzaturaViaggio.attrezzatura)
        .filter(Attrezzatura.stato == AttrezzaturaStatoEnum.in_trasporto)
        .all()
    )
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
    autisti = db.query(User).filter(User.role == RoleEnum.driver, User.is_active.is_(True)).order_by(User.full_name, User.email).all()
    mezzi = (
        db.query(Veicolo)
        .filter(Veicolo.visibile_trasporti.is_(True))
        .order_by(Veicolo.marca.asc(), Veicolo.modello.asc(), Veicolo.targa.asc())
        .all()
    )
    return render_template(templates, request, "manager/trasporti/new_trip.html", {"autisti": autisti, "mezzi": mezzi}, db, current_user)


@router.post("/manager/trasporti/nuovo", response_class=HTMLResponse)
@router.post("/manager/trasporti/viaggi/nuovo", response_class=HTMLResponse, name="manager_trasporti_viaggi_create")
def manager_trasporti_viaggi_create(
    request: Request,
    codice_viaggio: str = Form(...),
    data_partenza: str = Form(...),
    data_arrivo_prevista: str | None = Form(None),
    autista_id: int | None = Form(None),
    mezzo_id: int | None = Form(None),
    origine: str = Form(...),
    destinazione: str = Form(...),
    tappa_destinazione: list[str] = Form(default=[]),
    tipo_attrezzatura: list[str] = Form(default=[]),
    quantita: list[str] = Form(default=[]),
    richiesta_tappa_idx: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    viaggio = TrasportoViaggio(
        codice_viaggio=codice_viaggio.strip().upper(),
        data_partenza=datetime.strptime(data_partenza, "%Y-%m-%d").date(),
        data_arrivo_prevista=datetime.strptime(data_arrivo_prevista, "%Y-%m-%d").date() if data_arrivo_prevista else None,
        autista_id=autista_id,
        mezzo_id=mezzo_id,
        origine=origine.strip(),
        destinazione=destinazione.strip(),
        stato=TrasportoStatoEnum.programmato,
    )
    db.add(viaggio)
    db.flush()

    tappe_clean = [t.strip() for t in tappa_destinazione if (t or "").strip()]
    if not tappe_clean:
        tappe_clean = [destinazione.strip()]

    tappe: list[TrasportoTappa] = []
    for idx, dest in enumerate(tappe_clean, start=1):
        tappa = TrasportoTappa(viaggio_id=viaggio.id, ordine=idx, destinazione=dest)
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


@router.get("/manager/trasporti/viaggi/{viaggio_id}", response_class=HTMLResponse, name="manager_trasporti_viaggi_detail")
def manager_trasporti_viaggi_detail(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    autisti = db.query(User).filter(User.role == RoleEnum.driver, User.is_active.is_(True)).order_by(User.full_name, User.email).all()
    viaggio = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.autista),
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    assigned_counts: dict[str, list[str]] = {}
    for ass in viaggio.assegnazioni_attrezzature:
        key = (ass.attrezzatura.tipo or "").strip().lower()
        assigned_counts.setdefault(key, []).append(ass.attrezzatura.codice)

    equipment_panel = []
    for req in viaggio.richieste_attrezzature:
        key = (req.tipo_attrezzatura or "").strip().lower()
        codes = assigned_counts.get(key, [])
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
        {"viaggio": viaggio, "autisti": autisti, "equipment_panel": equipment_panel},
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
        autista = db.query(User).filter(User.id == autista_id, User.role == RoleEnum.driver, User.is_active.is_(True)).first()
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
        .options(joinedload(TrasportoViaggio.mezzo), joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa), joinedload(TrasportoViaggio.tappe))
        .filter(TrasportoViaggio.autista_id == current_user.id)
        .order_by(TrasportoViaggio.data_partenza.desc())
        .all()
    )

    viaggi_disponibili = (
        db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa), joinedload(TrasportoViaggio.tappe))
        .filter(TrasportoViaggio.autista_id.is_(None))
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
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
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.tappa_destinazione),
        )
        .filter(TrasportoViaggio.autista_id == current_user.id, TrasportoViaggio.data_partenza == today)
        .order_by(TrasportoViaggio.id.desc())
        .first()
    )
    richieste = []
    if viaggio:
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
            joinedload(TrasportoViaggio.richieste_attrezzature).joinedload(TrasportoRichiestaAttrezzatura.tappa),
            joinedload(TrasportoViaggio.tappe),
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
            if att.id in remaining_ids:
                att.posizione_attuale = "camion"
                ass.scaricato = False
                movement_dest = "camion"
            else:
                att.posizione_attuale = tappa_dest
                ass.scaricato = True
                movement_dest = tappa_dest
            att.stato = AttrezzaturaStatoEnum.disponibile
            db.add(
                MovimentoAttrezzatura(
                    attrezzatura_id=att.id,
                    viaggio_id=viaggio.id,
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
    if not has_perm(current_user, "trasporti.assigned.read") and not has_perm(current_user, "manager.access"):
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
    _ensure_manager(current_user)
    movimenti = (
        db.query(MovimentoAttrezzatura)
        .options(
            joinedload(MovimentoAttrezzatura.attrezzatura),
            joinedload(MovimentoAttrezzatura.viaggio),
            joinedload(MovimentoAttrezzatura.autista),
        )
        .order_by(MovimentoAttrezzatura.data.desc())
        .limit(200)
        .all()
    )
    return render_template(templates, request, "manager/trasporti/movimenti.html", {"movimenti": movimenti}, db, current_user)
