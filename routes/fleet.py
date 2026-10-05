from datetime import date, time
from uuid import uuid4
from typing import Literal
import io
import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from auth import get_current_active_user_html
from database import get_db
from models import (FleetJourney, FleetLoad, FleetOperation, FleetEvent, TrasportoViaggio,
    TrasportoTappa, TrasportoStatoEnum, User, Attrezzatura, AttrezzaturaStatoEnum, MovimentoAttrezzatura)
from models.veicoli import Veicolo
from permissions import can_access_manager_area, has_perm, can_access_logistics_area
from services.fleet import source, inventory, move, build_route, delivery_history
from utils.places import get_selectable_places, get_place_by_value
from template_context import register_manager_badges, render_template

router = APIRouter(tags=['parco'])
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


def manager(user):
    if not can_access_manager_area(user):
        raise HTTPException(403, 'Permessi insufficienti')


def access(db, trip_id, user, lock=False):
    query = db.query(FleetJourney).filter_by(trip_id=trip_id)
    journey = (query.with_for_update().populate_existing() if lock else query).first()
    trip = db.get(TrasportoViaggio, trip_id)
    if not journey or not trip or not (can_access_logistics_area(user) or
            (has_perm(user, 'trasporti.assigned.read') and trip.autista_id == user.id)):
        raise HTTPException(404, 'Viaggio non trovato')
    return journey, trip


def operator(trip, user):
    if not can_access_manager_area(user) and not (has_perm(user, 'trasporti.assigned.read') and trip.autista_id == user.id):
        raise HTTPException(403, 'Solo l’autista assegnato o il responsabile può registrare gli esiti')


def choices(db):
    from routes.trasporti import _load_trip_form_dependencies
    drivers, vehicles, places = _load_trip_form_dependencies(db)
    return dict(assets=inventory(db), places=[dict(value=p.value, label=p.label) for p in places],
        drivers=[dict(id=d.id, name=d.full_name or d.email) for d in drivers],
        vehicles=[dict(id=v.id, name=f'{v.targa} · {v.marca} {v.modello}') for v in vehicles])


@router.get('/manager/parco', name='fleet_home')
@router.get('/manager/trasporti/organizza', name='fleet_new')
def home(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    manager(user)
    editing = None
    if request.query_params.get('edit_id'):
        try:
            ident = int(request.query_params['edit_id'])
        except ValueError:
            raise HTTPException(400, 'Viaggio non valido')
        j, t = access(db, ident, user)
        loads = db.query(FleetLoad).filter_by(trip_id=ident).all()
        editing = dict(id=ident, revision=j.revision, day=str(t.data_partenza), hour=str(t.orario_partenza)[:5],
            driver=t.autista_id, vehicle=t.mezzo_id, start=j.route[0],
            back=j.route[-1]==j.route[0], moves=[dict(key=l.asset_key, origin=l.origin, destination=l.destination, reason=l.reason) for l in loads])
    data = choices(db)
    if editing:
        for a in data['assets']:
            if a['booked']==editing['id']:
                a['unavailable']=False
    return render_template(templates, request, 'manager/fleet.html',
        {'fleet_boot': dict(mode='new' if request.url.path.endswith('organizza') else 'park', editing=editing, **data)}, db, user)


@router.get('/logistica/viaggi/{trip_id}', name='fleet_trip')
def trip_page(trip_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    journey, trip = access(db, trip_id, user)
    return render_template(templates, request, 'manager/fleet.html',
        {'fleet_boot': dict(mode='trip', journey=serialize(db, journey, trip),
                            can_edit=can_access_manager_area(user), can_operate=can_access_manager_area(user) or trip.autista_id == user.id)}, db, user)


class MoveInput(BaseModel):
    key: str = Field(max_length=80)
    origin: str = Field(max_length=80)
    destination: str = Field(max_length=80)
    reason: str = Field(default='Trasferimento', max_length=100)


class PlanInput(BaseModel):
    edit_id: int | None = None
    start: str = Field(max_length=80)
    return_to_start: bool = True
    moves: list[MoveInput] = Field(min_length=1, max_length=150)


class CreateInput(PlanInput):
    token: str = Field(min_length=16, max_length=64)
    day: date
    hour: time
    driver_id: int
    vehicle_id: int


def validate_plan(db, payload, lock=False, exclude_trip=None):
    keys = [r.key for r in payload.moves]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, 'Un bene può comparire una sola volta nel viaggio')
    if lock:
        for key in sorted(keys):
            source(db, key, lock=True)
    assets = {a['key']: a for a in inventory(db)}
    places = {p.value: p for p in get_selectable_places(db)}
    if payload.start not in places:
        raise HTTPException(400, 'Scegli il luogo di partenza del camion')
    for row in payload.moves:
        asset = assets.get(row.key)
        if not asset or asset['family'] == 'Veicoli':
            raise HTTPException(400, 'Scegli macchinari o attrezzature da trasportare')
        if asset['unavailable'] and (exclude_trip is None or asset['booked'] != exclude_trip):
            raise HTTPException(409, f'{asset["name"]}: già previsto in un altro viaggio o in trasporto')
        if row.origin not in places or row.destination not in places or row.origin == row.destination:
            raise HTTPException(400, 'Ritiro e consegna devono essere luoghi diversi e attivi')
        if asset['place'] and asset['place'] != row.origin:
            raise HTTPException(409, f'Ubicazione cambiata per {asset["name"]}. Ricarica il parco.')
        if not row.reason.strip():
            raise HTTPException(400, 'Indica il motivo dello spostamento')
    route, moves = build_route(payload.start, [r.model_dump() for r in payload.moves], payload.return_to_start)
    return route, moves, assets


@router.post('/api/parco/anteprima')
def preview(payload: PlanInput, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    manager(user)
    if payload.edit_id:
        access(db,payload.edit_id,user)
    route, moves, _ = validate_plan(db, payload,exclude_trip=payload.edit_id)
    return dict(route=route, moves=moves)


@router.post('/api/parco/viaggi')
def create(payload: CreateInput, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    manager(user)
    previous = db.query(FleetJourney).filter_by(token=payload.token).first()
    if previous:
        if previous.created_by != user.id:
            raise HTTPException(409, 'Identificativo già utilizzato')
        return dict(url=f'/logistica/viaggi/{previous.trip_id}')
    # Carrier lock serializes conflicting allocations and validates its real record.
    vehicle = db.query(Veicolo).filter_by(id=payload.vehicle_id, visibile_trasporti=True).with_for_update().first()
    driver = db.query(User).filter_by(id=payload.driver_id, is_active=True).with_for_update().first()
    if not vehicle or not driver or not has_perm(driver, 'trasporti.assigned.read'):
        raise HTTPException(400, 'Scegli un camion disponibile ai trasporti e un autista attivo')
    busy = db.query(TrasportoViaggio).filter(TrasportoViaggio.data_partenza == payload.day,
        TrasportoViaggio.orario_partenza == payload.hour, TrasportoViaggio.stato != TrasportoStatoEnum.completato,
        ((TrasportoViaggio.mezzo_id == payload.vehicle_id) | (TrasportoViaggio.autista_id == payload.driver_id))).first()
    if busy:
        raise HTTPException(409, 'Camion o autista già assegnato a un viaggio con questa partenza')
    route, moves, assets = validate_plan(db, payload, lock=True)
    places = {p.value: p for p in get_selectable_places(db)}
    def fields(p):
        return dict(site_id=p.id if p.kind == 'site' else None, depot_id=p.id if p.kind == 'depot' else None)
    trip = TrasportoViaggio(codice_viaggio='TR-'+payload.day.strftime('%Y%m%d')+'-'+uuid4().hex[:8].upper(),
        data_partenza=payload.day, orario_partenza=payload.hour, autista_id=driver.id, mezzo_id=vehicle.id,
        origine=places[route[0]].name, destinazione=places[route[-1]].name,
        stato=TrasportoStatoEnum.programmato, materiali_attrezzature=', '.join(assets[r['key']]['name'] for r in moves))
    for prefix, p in [('origine', places[route[0]]), ('destinazione', places[route[-1]])]:
        for k, v in fields(p).items():
            setattr(trip, prefix+'_'+k, v)
    try:
        db.add(trip); db.flush()
        journey = FleetJourney(trip_id=trip.id, token=payload.token, route=route, created_by=user.id)
        db.add(journey)
        for i, value in enumerate(route[1:], 1):
            db.add(TrasportoTappa(viaggio_id=trip.id, ordine=i, destinazione=places[value].name, **fields(places[value])))
        for row in moves:
            load = FleetLoad(trip_id=trip.id, asset_key=row['key'], reservation=row['key'], origin=row['origin'],
                destination=row['destination'], pickup=row['pickup'], delivery=row['delivery'], reason=row['reason'],
                technical_state=assets[row['key']]['technical'])
            db.add(load); db.flush()
            db.add_all([FleetOperation(load_id=load.id, stop=load.pickup, kind='load'),
                        FleetOperation(load_id=load.id, stop=load.delivery, kind='unload')])
        db.add(FleetEvent(trip_id=trip.id, actor_id=user.id, text='Viaggio creato. Ubicazioni invariate.'))
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.query(FleetJourney).filter_by(token=payload.token, created_by=user.id).first()
        if previous:
            return dict(url=f'/logistica/viaggi/{previous.trip_id}')
        raise HTTPException(409, 'Un bene è stato prenotato da un altro viaggio. Ricarica la selezione.')
    return dict(url=f'/logistica/viaggi/{trip.id}')


def serialize(db, journey, trip):
    loads = db.query(FleetLoad).filter_by(trip_id=trip.id).order_by(FleetLoad.id).all()
    assets = {a['key']: a for a in inventory(db)}
    places = {p.value: p.label for p in get_selectable_places(db, include_inactive=True)}
    operations = db.query(FleetOperation).join(FleetLoad).filter(FleetLoad.trip_id == trip.id).order_by(FleetOperation.id).all()
    return dict(id=trip.id, code=trip.codice_viaggio, date=str(trip.data_partenza), hour=str(trip.orario_partenza or '')[:5],
        driver=trip.autista.full_name or trip.autista.email if trip.autista else '',
        vehicle=trip.mezzo.targa if trip.mezzo else '', revision=journey.revision,
        route=[dict(value=v, label=places.get(v, v)) for v in journey.route], stop=journey.current_stop,
        finished=journey.finished, editable=not journey.finished and journey.current_stop==0 and all(o.result=='pending' for o in operations), loads=[dict(id=l.id, asset=assets.get(l.asset_key, dict(name=l.asset_key, code=l.asset_key)),
            origin=places.get(l.origin, l.origin), destination=places.get(l.destination,l.destination),
            state=l.state) for l in loads], operations=[dict(id=o.id, load_id=o.load_id, stop=o.stop, kind=o.kind,
            result=o.result, reason=o.reason or '') for o in operations],
        events=[dict(text=e.text, at=e.created_at.isoformat()) for e in db.query(FleetEvent).filter_by(trip_id=trip.id).order_by(FleetEvent.id).all()])


class ActionInput(BaseModel):
    revision: int
    action: Literal['done', 'not_done', 'correct', 'next', 'recover']
    operation_id: int | None = None
    reason: str = Field(default='', max_length=500)
    destination: str | None = Field(default=None, max_length=80)


class UpdateInput(CreateInput):
    revision: int


@router.post('/api/parco/viaggi/{trip_id}/modifica')
def update_trip(trip_id: int, payload: UpdateInput, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    manager(user)
    journey, trip=access(db,trip_id,user,lock=True)
    operations=db.query(FleetOperation).join(FleetLoad).filter(FleetLoad.trip_id==trip_id).all()
    if journey.revision!=payload.revision or journey.finished or journey.current_stop or any(o.result!='pending' for o in operations):
        raise HTTPException(409,'Viaggio aggiornato o già iniziato: non è possibile cambiare la pianificazione')
    vehicle=db.query(Veicolo).filter_by(id=payload.vehicle_id,visibile_trasporti=True).with_for_update().first()
    driver=db.query(User).filter_by(id=payload.driver_id,is_active=True).with_for_update().first()
    if not vehicle or not driver or not has_perm(driver,'trasporti.assigned.read'):
        raise HTTPException(400,'Camion o autista non valido')
    conflict=db.query(TrasportoViaggio).filter(TrasportoViaggio.id!=trip_id,TrasportoViaggio.data_partenza==payload.day,
        TrasportoViaggio.orario_partenza==payload.hour,TrasportoViaggio.stato!=TrasportoStatoEnum.completato,
        ((TrasportoViaggio.mezzo_id==vehicle.id)|(TrasportoViaggio.autista_id==driver.id))).first()
    if conflict:
        raise HTTPException(409,'Camion o autista già impegnato con questa partenza')
    route, moves, assets=validate_plan(db,payload,lock=True,exclude_trip=trip_id)
    old=db.query(FleetLoad).filter_by(trip_id=trip_id).all()
    for o in operations:db.delete(o)
    for l in old:db.delete(l)
    for stop in list(trip.tappe):db.delete(stop)
    db.flush()
    trip.data_partenza,trip.orario_partenza=payload.day,payload.hour
    trip.autista_id,trip.mezzo_id=driver.id,vehicle.id
    trip.materiali_attrezzature=', '.join(assets[r['key']]['name'] for r in moves)
    for prefix,value in [('origine',route[0]),('destinazione',route[-1])]:
        p=get_place_by_value(db,value)
        setattr(trip,prefix,p.name)
        setattr(trip,prefix+'_site_id',p.id if p.kind=='site' else None)
        setattr(trip,prefix+'_depot_id',p.id if p.kind=='depot' else None)
    for i,value in enumerate(route[1:],1):
        p=get_place_by_value(db,value)
        db.add(TrasportoTappa(viaggio_id=trip_id,ordine=i,destinazione=p.name,site_id=p.id if p.kind=='site' else None,depot_id=p.id if p.kind=='depot' else None))
    for row in moves:
        l=FleetLoad(trip_id=trip_id,asset_key=row['key'],reservation=row['key'],origin=row['origin'],destination=row['destination'],
            pickup=row['pickup'],delivery=row['delivery'],reason=row['reason'],technical_state=assets[row['key']]['technical'])
        db.add(l);db.flush()
        db.add_all([FleetOperation(load_id=l.id,stop=l.pickup,kind='load'),FleetOperation(load_id=l.id,stop=l.delivery,kind='unload')])
    journey.route=route;journey.revision+=1
    db.add(FleetEvent(trip_id=trip_id,actor_id=user.id,text='Pianificazione modificata prima della partenza'))
    try:
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Un bene è stato prenotato da un altro viaggio')
    return dict(url=f'/logistica/viaggi/{trip_id}')


@router.post('/api/parco/viaggi/{trip_id}/esito')
def outcome(trip_id: int, payload: ActionInput, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    journey, trip = access(db, trip_id, user, lock=True)
    operator(trip, user)
    if journey.revision != payload.revision or journey.finished:
        raise HTTPException(409, 'Viaggio aggiornato da un altro dispositivo o già terminato. Ricarica la pagina.')
    loads = db.query(FleetLoad).filter_by(trip_id=trip_id).order_by(FleetLoad.id).all()
    ops = db.query(FleetOperation).join(FleetLoad).filter(FleetLoad.trip_id == trip_id).all()
    here = journey.route[journey.current_stop]
    op = next((o for o in ops if o.id == payload.operation_id and o.stop == journey.current_stop), None)
    text = ''
    if payload.action in ('done', 'not_done', 'correct'):
        if not op:
            raise HTTPException(400, 'Operazione non presente alla fermata attuale')
        load = next(l for l in loads if l.id == op.load_id)
        obj = source(db, load.asset_key, lock=True)
        if payload.action == 'correct':
            if any(later.load_id==op.load_id and later.kind==op.kind and later.id>op.id for later in ops):
                raise HTTPException(409,'Questo esito ha già un tentativo successivo: correggi l’ultima operazione')
            if not op.before or op.result not in ('yes','no'):
                raise HTTPException(409, 'Esito non correggibile')
            # Re-reserving a previously missed pickup can conflict with a newer plan.
            other = db.query(FleetLoad).filter(FleetLoad.reservation == load.asset_key, FleetLoad.id != load.id).first()
            if other:
                raise HTTPException(409, 'Il bene è stato assegnato a un altro viaggio')
            if op.result == 'yes':
                move(db, load.asset_key, op.before['place'])
                if isinstance(obj, Attrezzatura):
                    obj.stato = AttrezzaturaStatoEnum(op.before['state'])
                if op.kind == 'unload':
                    db.query(MovimentoAttrezzatura).filter_by(viaggio_id=trip_id, attrezzatura_id=int(load.asset_key.split(':')[1])).delete() if isinstance(obj, Attrezzatura) else None
            load.state, load.reservation = op.before['load_state'], load.asset_key
            for later in ops:
                if later.load_id == load.id and later.result == 'skip':
                    later.result, later.reason = 'pending', None
            op.result, op.reason, op.before = 'pending', None, None
            text = f'{load.asset_key}: esito riaperto per correzione'
        else:
            if op.result != 'pending':
                raise HTTPException(409, 'Esito già registrato. Usa Correggi.')
            if payload.action == 'not_done' and not payload.reason.strip():
                raise HTTPException(400, 'Scrivi il motivo dell’operazione non eseguita')
            if (op.kind == 'load' and load.state != 'planned') or (op.kind == 'unload' and load.state != 'loaded'):
                raise HTTPException(409, 'Stato del carico non compatibile')
            current = next((a for a in inventory(db) if a['key'] == load.asset_key), None)
            if op.kind == 'load' and current and current['place'] and current['place'] != here:
                raise HTTPException(409, 'Il bene non risulta più nel luogo di ritiro')
            op.before = dict(place=here if op.kind == 'load' else None,
                             state=obj.stato.value if isinstance(obj, Attrezzatura) else None, load_state=load.state)
            op.result, op.reason = ('yes', None) if payload.action == 'done' else ('no', payload.reason.strip())
            if op.result == 'yes':
                if op.kind == 'load' and isinstance(obj, Attrezzatura):
                    load.technical_state = 'manutenzione' if obj.stato == AttrezzaturaStatoEnum.manutenzione else 'operativo'
                move(db, load.asset_key, None if op.kind == 'load' else here)
                load.state = 'loaded' if op.kind == 'load' else 'delivered'
                if isinstance(obj, Attrezzatura):
                    # Maintenance is a technical state: transport never clears it.
                    obj.stato = (AttrezzaturaStatoEnum.manutenzione if load.technical_state == 'manutenzione' or obj.stato == AttrezzaturaStatoEnum.manutenzione else
                                 AttrezzaturaStatoEnum.in_trasporto if op.kind == 'load' else
                                 AttrezzaturaStatoEnum.in_uso if here.startswith('site:') else AttrezzaturaStatoEnum.disponibile)
                if op.kind == 'unload':
                    load.reservation = None
                    delivery_history(db, load, trip, user)
            elif op.kind == 'load':
                load.state, load.reservation = 'deferred', None
                for later in ops:
                    if later.load_id == load.id and later.kind == 'unload' and later.result == 'pending':
                        later.result, later.reason = 'skip', payload.reason.strip()
            text = f'{load.asset_key}: {"Carico" if op.kind == "load" else "Scarico"} {"fatto" if op.result == "yes" else "non fatto — "+op.reason}'
            trip.stato = TrasportoStatoEnum.in_carico if journey.current_stop == 0 else TrasportoStatoEnum.in_viaggio
    else:
        if any(o.stop == journey.current_stop and o.result == 'pending' for o in ops):
            raise HTTPException(409, 'Registra un esito per ogni operazione')
        cargo = [l for l in loads if l.state == 'loaded']
        if payload.action == 'recover':
            if journey.current_stop != len(journey.route)-1 or not cargo:
                raise HTTPException(400, 'Recupero disponibile a fine giro con beni ancora a bordo')
            destination = get_place_by_value(db, payload.destination, include_inactive=False)
            if not destination:
                raise HTTPException(400, 'Scegli dove scaricare i beni rimasti')
            if destination.value != here:
                journey.route = [*journey.route, destination.value]
                journey.current_stop += 1
                db.add(TrasportoTappa(viaggio_id=trip.id, ordine=journey.current_stop, destinazione=destination.name,
                    site_id=destination.id if destination.kind=='site' else None, depot_id=destination.id if destination.kind=='depot' else None))
                trip.destinazione=destination.name
                trip.destinazione_site_id=destination.id if destination.kind=='site' else None
                trip.destinazione_depot_id=destination.id if destination.kind=='depot' else None
            for load in cargo:
                load.destination = destination.value
                db.add(FleetOperation(load_id=load.id, stop=journey.current_stop, kind='unload'))
            text = 'Scarichi rimasti da completare a '+destination.label
        elif journey.current_stop < len(journey.route)-1:
            journey.current_stop += 1
            if trip.mezzo_id:
                move(db, f'vehicle:{trip.mezzo_id}', journey.route[journey.current_stop])
            trip.stato = TrasportoStatoEnum.in_viaggio
            text = 'Fermata raggiunta: '+journey.route[journey.current_stop]
        else:
            if cargo:
                raise HTTPException(409, 'Ci sono ancora beni sul camion: organizza lo scarico')
            journey.finished = True
            trip.stato = TrasportoStatoEnum.completato
            text = 'Viaggio terminato; esiti e motivi conservati'
    if trip.mezzo_id:
        move(db, f'vehicle:{trip.mezzo_id}', journey.route[journey.current_stop])
    journey.revision += 1
    db.add(FleetEvent(trip_id=trip_id, actor_id=user.id, text=text))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Bene prenotato da un altro viaggio. Ricarica la pagina.')
    return serialize(db, journey, trip)


@router.get('/api/parco/viaggi/{trip_id}')
def read_trip(trip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    j, t = access(db, trip_id, user)
    return serialize(db, j, t)


@router.get('/manager/parco/qr/{kind}/{asset_id}', name='fleet_qr')
def label(kind: str, asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    manager(user)
    key = f'{kind}:{asset_id}'
    asset = next((a for a in inventory(db) if a['key'] == key), None)
    if not asset:
        raise HTTPException(404, 'Bene non trovato')
    qr = segno.make(asset['qr'], error='m', micro=False)
    buf = io.BytesIO(); qr.save(buf, kind='svg', scale=8)
    return Response(buf.getvalue(), media_type='image/svg+xml')
