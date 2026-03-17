from __future__ import annotations

from datetime import date, datetime

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
    TrasportoAttrezzaturaViaggio,
    TrasportoRichiestaAttrezzatura,
    TrasportoStatoEnum,
    TrasportoViaggio,
    User,
)
from permissions import has_perm
from models.veicoli import Veicolo
from template_context import register_manager_badges, render_template

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["trasporti"])


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _ensure_driver(user: User) -> None:
    if not has_perm(user, "trasporti.assigned.read"):
        raise HTTPException(status_code=403, detail="Accesso riservato agli autisti")


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
            query = query.filter(TrasportoViaggio.destinazione.ilike(f"%{destinazione.strip()}%"))
        if selected_data:
            query = query.filter(TrasportoViaggio.data_partenza == selected_data)
        return query

    future_trips = (
        _apply_filters(
            db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.autista), joinedload(TrasportoViaggio.mezzo))
        .filter(TrasportoViaggio.data_partenza >= today)
        )
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
    active_trips = (
        _apply_filters(
            db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.autista), joinedload(TrasportoViaggio.mezzo))
        .filter(TrasportoViaggio.stato.in_([TrasportoStatoEnum.in_carico, TrasportoStatoEnum.in_viaggio, TrasportoStatoEnum.arrivato]))
        )
        .order_by(TrasportoViaggio.data_partenza.desc())
        .all()
    )
    completed_trips = (
        _apply_filters(
            db.query(TrasportoViaggio)
        .options(joinedload(TrasportoViaggio.autista), joinedload(TrasportoViaggio.mezzo))
        .filter(TrasportoViaggio.stato == TrasportoStatoEnum.completato)
        )
        .order_by(TrasportoViaggio.data_partenza.desc())
        .limit(20)
        .all()
    )
    autisti = db.query(User).filter(User.role == RoleEnum.driver).order_by(User.full_name, User.email).all()
    mezzi = db.query(Veicolo).filter(Veicolo.visibile_trasporti.is_(True)).order_by(Veicolo.marca, Veicolo.modello).all()
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
    return render_template(
        templates,
        request,
        "manager/trasporti/new_trip.html",
        {"autisti": autisti, "mezzi": mezzi},
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
    origine: str = Form(...),
    destinazione: str = Form(...),
    tipo_attrezzatura: list[str] = Form(default=[]),
    quantita: list[str] = Form(default=[]),
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

    for idx, tipo in enumerate(tipo_attrezzatura):
        tipo_clean = (tipo or "").strip().lower()
        if not tipo_clean:
            continue
        q_raw = quantita[idx] if idx < len(quantita) else "1"
        q = max(1, int(q_raw or 1))
        db.add(
            TrasportoRichiestaAttrezzatura(
                viaggio_id=viaggio.id,
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
            joinedload(TrasportoViaggio.richieste_attrezzature),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
        )
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )
    if not viaggio:
        return RedirectResponse(url=request.url_for("manager_trasporti_dashboard"), status_code=303)

    return render_template(
        templates,
        request,
        "manager/trasporti/trip_detail.html",
        {"viaggio": viaggio, "autisti": autisti},
        db,
        current_user,
    )


@router.post(
    "/manager/trasporti/viaggi/{viaggio_id}/autista",
    response_class=HTMLResponse,
    name="manager_trasporti_viaggi_autista_update",
)
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
        autista = (
            db.query(User)
            .filter(User.id == autista_id, User.role == RoleEnum.driver, User.is_active.is_(True))
            .first()
        )
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
        .options(joinedload(TrasportoViaggio.mezzo), joinedload(TrasportoViaggio.richieste_attrezzature))
        .filter(TrasportoViaggio.autista_id == current_user.id)
        .order_by(TrasportoViaggio.data_partenza.desc())
        .all()
    )

    viaggi_disponibili = (
        db.query(TrasportoViaggio)
        .options(
            joinedload(TrasportoViaggio.mezzo),
            joinedload(TrasportoViaggio.richieste_attrezzature),
        )
        .filter(
            TrasportoViaggio.autista_id.is_(None),
            TrasportoViaggio.stato == TrasportoStatoEnum.programmato,
        )
        .order_by(TrasportoViaggio.data_partenza.asc())
        .all()
    )
    return render_template(
        templates,
        request,
        "driver/trasporti/assigned_trips.html",
{
    "viaggi_assegnati": viaggi_assegnati,
    "viaggi_disponibili": viaggi_disponibili
},
        db,
        current_user,
    )


@router.post(
    "/driver/trasporti/viaggi/{viaggio_id}/prendi",
    response_class=HTMLResponse,
    name="driver_trasporti_viaggi_prendi",
)
def driver_trasporti_viaggi_prendi(
    viaggio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):

    _ensure_driver(current_user)

    viaggio = (
        db.query(TrasportoViaggio)
        .filter(TrasportoViaggio.id == viaggio_id)
        .first()
    )

    if not viaggio:
        return RedirectResponse(
            url=request.url_for("driver_trasporti_viaggi"),
            status_code=303,
        )

    if viaggio.autista_id is None:
        viaggio.autista_id = current_user.id
        db.commit()

    return RedirectResponse(
        url=request.url_for("driver_trasporti_viaggi"),
        status_code=303,
    )
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
            joinedload(TrasportoViaggio.richieste_attrezzature),
            joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura),
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
            if raw_attrezzatura_id is None:
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
                db.add(
                    TrasportoAttrezzaturaViaggio(
                        viaggio_id=viaggio.id,
                        attrezzatura_id=attrezzatura.id,
                        caricato=True,
                    )
                )

    viaggio.stato = TrasportoStatoEnum.in_carico
    db.commit()
    return RedirectResponse(url=request.url_for("driver_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


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
        .options(joinedload(TrasportoViaggio.assegnazioni_attrezzature).joinedload(TrasportoAttrezzaturaViaggio.attrezzatura))
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
        now = datetime.utcnow()
        for ass in viaggio.assegnazioni_attrezzature:
            att = ass.attrezzatura
            att.posizione_attuale = viaggio.destinazione
            att.stato = AttrezzaturaStatoEnum.disponibile
            db.add(
                MovimentoAttrezzatura(
                    attrezzatura_id=att.id,
                    viaggio_id=viaggio.id,
                    origine=viaggio.origine,
                    destinazione=viaggio.destinazione,
                    data=now,
                    autista_id=current_user.id,
                )
            )

    db.commit()
    return RedirectResponse(url=request.url_for("driver_trasporti_viaggi_detail", viaggio_id=viaggio.id), status_code=303)


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
    return render_template(
        templates,
        request,
        "manager/trasporti/movimenti.html",
        {"movimenti": movimenti},
        db,
        current_user,
    )
