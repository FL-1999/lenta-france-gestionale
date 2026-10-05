"""Inventory projection and physical movements shared by the fleet and driver UI."""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from models import (Machine, MachineSiteAssignment, Attrezzatura, AttrezzaturaStatoEnum,
                    FleetPosition, FleetLoad, TrasportoAttrezzaturaViaggio, TrasportoViaggio,
                    TrasportoStatoEnum, MovimentoAttrezzatura)
from models.veicoli import Veicolo
from utils.places import get_selectable_places, get_place_by_value

MODELS = {'machine': Machine, 'equipment': Attrezzatura, 'vehicle': Veicolo}


def source(db, key, lock=False):
    try:
        kind, ident = key.split(':')
        model = MODELS[kind]
        ident = int(ident)
    except (KeyError, ValueError, AttributeError):
        raise HTTPException(400, 'Identificativo del bene non valido')
    query = db.query(model).filter(model.id == ident)
    obj = (query.with_for_update() if lock else query).first()
    if obj is None:
        raise HTTPException(404, 'Bene non trovato')
    return obj


def inventory(db):
    places = get_selectable_places(db, include_inactive=True)
    by_name = {}
    for place in places:
        by_name.setdefault(place.name.strip().casefold(), []).append(place.value)
        by_name.setdefault(place.label.strip().casefold(), []).append(place.value)
    positions = {p.asset_key: p.place for p in db.query(FleetPosition).all()}
    reservations = {p.asset_key: p for p in db.query(FleetLoad).filter(FleetLoad.reservation.isnot(None)).all()}
    old_loads = {a.attrezzatura_id for a in db.query(TrasportoAttrezzaturaViaggio).join(TrasportoViaggio)
                 .filter(TrasportoViaggio.stato != TrasportoStatoEnum.completato,
                         TrasportoAttrezzaturaViaggio.scaricato.is_(False)).all()}
    result = []
    for kind, model in MODELS.items():
        query = db.query(model)
        if kind == 'machine':
            query = query.filter(Machine.is_active.is_(True)).options(selectinload(Machine.assignments), selectinload(Machine.machine_type_rel))
        for obj in query.all():
            key = f'{kind}:{obj.id}'
            place = positions.get(key)
            if kind == 'machine':
                category = obj.machine_type_rel.label_it if obj.machine_type_rel else getattr(obj.machine_type, 'value', None) or 'Altro'
                name, code = obj.name, obj.code or f'MAC-{obj.id:05d}'
                family = 'Attrezzature' if 'benn' in (category+' '+name).lower() else 'Macchinari'
                category = 'Benne' if family == 'Attrezzature' else category
                raw = next((a.location_label for a in obj.assignments if a.unassigned_at is None), None)
                if obj.site_id:
                    place = f'site:{obj.site_id}'
                elif raw and len(by_name.get(raw.casefold(), [])) == 1:
                    place = by_name[raw.casefold()][0]
                elif place and place.startswith('site:'):
                    place = None
                technical = obj.status or 'attivo'
                use = 'In uso' if obj.site_id else 'Libero'
                detail = f'/manager/macchinari/{obj.id}'
                qr = 'LF:'+key
            elif kind == 'equipment':
                name, code, category, family = obj.nome, obj.codice, obj.tipo, 'Attrezzature'
                raw = (obj.posizione_attuale or '').strip()
                matches = by_name.get(raw.casefold(), [])
                if len(matches) == 1:
                    place = matches[0]
                elif place and not any(p.value == place and raw in (p.name, p.label) for p in places):
                    place = None
                technical = 'manutenzione' if obj.stato == AttrezzaturaStatoEnum.manutenzione else 'operativo'
                use = 'In uso' if obj.stato == AttrezzaturaStatoEnum.in_uso else 'Libero'
                if obj.stato == AttrezzaturaStatoEnum.in_trasporto:
                    use = 'In trasporto'
                detail, qr = f'/manager/attrezzature/{obj.id}/modifica', obj.qr_code
            else:
                name, code, category, family = f'{obj.marca} {obj.modello}', obj.targa or f'VEI-{obj.id:05d}', obj.categoria or 'Altro', 'Veicoli'
                technical, use = 'operativo', 'Libero'
                detail, qr = f'/manager/veicoli/{obj.id}', 'LF:'+key
            load = reservations.get(key)
            if load and load.state == 'loaded':
                place, use = None, 'Sul camion'
            result.append(dict(key=key, name=name, code=code, category=category, family=family,
                               place=place, location='Sul camion' if use == 'Sul camion' else next((p.label for p in places if p.value == place), 'Da indicare'),
                               technical=technical, use=use, detail=detail, qr=qr,
                               booked=load.trip_id if load else None,
                               unavailable=bool(load or (kind == 'equipment' and (obj.id in old_loads or use == 'In trasporto')))))
    return sorted(result, key=lambda a: (a['family'], a['name'].casefold()))


def move(db, key, place_value):
    obj = source(db, key, lock=True)
    place = get_place_by_value(db, place_value) if place_value else None
    pos = db.get(FleetPosition, key)
    if not pos:
        pos = FleetPosition(asset_key=key)
        db.add(pos)
    pos.place, pos.updated_at = place_value, datetime.utcnow()
    if isinstance(obj, Attrezzatura):
        obj.posizione_attuale = place.name if place else 'camion'
    elif isinstance(obj, Machine):
        now = datetime.utcnow()
        for assignment in db.query(MachineSiteAssignment).filter_by(machine_id=obj.id, unassigned_at=None).all():
            assignment.unassigned_at = now
        obj.site_id = place.id if place and place.kind == 'site' else None
        db.add(MachineSiteAssignment(machine_id=obj.id, site_id=obj.site_id,
                                     location_label=place.name if place else 'Sul camion', assigned_at=now))


def delivery_history(db, load, trip, user):
    if not load.asset_key.startswith('equipment:'):
        return
    origin = get_place_by_value(db, load.origin)
    destination = get_place_by_value(db, load.destination)
    db.add(MovimentoAttrezzatura(attrezzatura_id=int(load.asset_key.split(':')[1]), viaggio_id=trip.id,
        origine=origin.name, destinazione=destination.name, autista_id=user.id,
        origine_site_id=origin.id if origin.kind == 'site' else None,
        origine_depot_id=origin.id if origin.kind == 'depot' else None,
        destinazione_site_id=destination.id if destination.kind == 'site' else None,
        destinazione_depot_id=destination.id if destination.kind == 'depot' else None))


def build_route(start, moves, return_to_start):
    """Deterministic pickup-before-delivery route, including revisits when needed."""
    remaining = list(moves)
    aboard, route, planned = [], [start], {}
    while remaining or aboard:
        here, index = route[-1], len(route)-1
        for row in aboard[:]:
            if row['destination'] == here:
                planned[row['key']]['delivery'] = index
                aboard.remove(row)
        for row in remaining[:]:
            if row['origin'] == here:
                planned[row['key']] = {**row, 'pickup': index}
                aboard.append(row)
                remaining.remove(row)
        if remaining or aboard:
            route.append(next((r['destination'] for r in aboard if r['destination'] != start), aboard[0]['destination']) if aboard else remaining[0]['origin'])
    if return_to_start and route[-1] != start:
        route.append(start)
    return route, list(planned.values())
