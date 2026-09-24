"""Operational stock overview; valuation uses the article's reference cost."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import case, func, or_
from sqlalchemy.orm import joinedload

from models import (MagazzinoItem as Item, MagazzinoMovimento as Movement,
                    MagazzinoRichiesta as Request, MagazzinoRichiestaStatusEnum as Status,
                    MagazzinoRichiestaPrioritaEnum as Priority, MagazzinoMovimentoTipoEnum as MovementType)


def valuation(db):
    total, priced, value, missing_stock = db.query(
        func.count(Item.id), func.count(Item.costo_unitario),
        func.coalesce(func.sum(Item.quantita_disponibile * Item.costo_unitario), 0),
        func.coalesce(func.sum(case(((Item.costo_unitario.is_(None)) &
                                     (Item.quantita_disponibile > 0), 1), else_=0)), 0),
    ).filter(Item.attivo.is_(True)).one()
    return dict(total=total, priced=priced, missing=total-priced, value=round(value, 2),
                missing_stock=missing_stock, coverage=round(priced * 100 / total) if total else 0)


def overview(db):
    active = db.query(Item).filter(Item.attivo.is_(True))
    low = active.filter(Item.soglia_minima.isnot(None), Item.quantita_disponibile <= Item.soglia_minima)
    empty = active.filter(Item.quantita_disponibile <= 0)
    open_states = (Status.in_attesa, Status.approvata, Status.parziale)
    requests = db.query(Request).filter(Request.stato.in_(open_states))
    queue = requests.options(joinedload(Request.cantiere)).order_by(
        case((Request.priorita == Priority.high, 0), else_=1),
        Request.data_necessaria.asc().nullslast(), Request.created_at, Request.id).limit(6).all()
    stock = active.filter(or_(Item.quantita_disponibile <= 0,
                              Item.quantita_disponibile <= Item.soglia_minima)).order_by(
        Item.quantita_disponibile, Item.nome, Item.id).limit(6).all()
    movements = db.query(Movement).options(joinedload(Movement.item)).order_by(
        Movement.created_at.desc(), Movement.id.desc()).limit(5).all()
    consumption = db.query(Item.id, Item.nome, Item.unita_misura,
        func.sum(Movement.quantita).label('total')).join(Movement, Movement.item_id == Item.id).filter(
        Movement.tipo == MovementType.scarico, Movement.created_at >= datetime.now() - timedelta(days=30)
        ).group_by(Item.id, Item.nome, Item.unita_misura).order_by(func.sum(Movement.quantita).desc(), Item.id).limit(10).all()
    return dict(valuation=valuation(db), low_count=low.count(), empty_count=empty.count(),
                waiting_count=requests.filter(Request.stato == Status.in_attesa).count(),
                preparing_count=requests.filter(Request.stato.in_((Status.approvata, Status.parziale))).count(),
                request_queue=queue, stock_attention=stock, recent_movements=movements,
                top_consumption=consumption, today=date.today(), today_movements=db.query(Movement).filter(
                    Movement.created_at >= datetime.combine(date.today(), time.min)).count())
