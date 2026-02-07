import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import (
    MagazzinoItem,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    PurchaseDelivery,
    PurchaseDeliveryLine,
    PurchaseOrder,
    PurchaseOrderLine,
    User,
)
from permissions import has_perm
from template_context import register_manager_badges, render_template

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["ordini"])

logger = logging.getLogger("lenta_france_gestionale.orders")
MAX_ORDER_NUMBER_RETRIES = 5


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _find_magazzino_item_by_description(
    db: Session,
    description: str | None,
) -> MagazzinoItem | None:
    if not description:
        return None
    normalized = description.strip()
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    item = (
        db.query(MagazzinoItem)
        .filter(func.lower(MagazzinoItem.codice) == normalized_lower)
        .first()
    )
    if item:
        return item
    return (
        db.query(MagazzinoItem)
        .filter(func.lower(MagazzinoItem.nome) == normalized_lower)
        .first()
    )


def _get_next_order_number(db: Session, order_date: date | None) -> str:
    target_year = (order_date or date.today()).year
    year_prefix = f"{target_year}-"

    year_order_exists = (
        db.query(PurchaseOrder.id)
        .filter(PurchaseOrder.order_number.like(f"{year_prefix}%"))
        .first()
    )
    if year_order_exists:
        max_year_value = (
            db.query(
                func.max(cast(func.substr(PurchaseOrder.order_number, 6), Integer))
            )
            .filter(PurchaseOrder.order_number.like(f"{year_prefix}%"))
            .scalar()
            or 0
        )
        return f"{year_prefix}{max_year_value + 1:04d}"

    max_value = (
        db.query(func.max(cast(PurchaseOrder.order_number, Integer))).scalar()
        or 0
    )
    return str(max_value + 1)


def _load_delivered_totals(db: Session, order_id: int) -> dict[int, float]:
    return {
        line_id: total
        for line_id, total in (
            db.query(
                PurchaseDeliveryLine.order_line_id,
                func.coalesce(func.sum(PurchaseDeliveryLine.qty_delivered), 0.0),
            )
            .join(
                PurchaseDelivery,
                PurchaseDelivery.id == PurchaseDeliveryLine.delivery_id,
            )
            .filter(
                PurchaseDelivery.order_id == order_id,
                PurchaseDelivery.confirmed.is_(True),
            )
            .group_by(PurchaseDeliveryLine.order_line_id)
            .all()
        )
    }


def _calculate_completion_percent(
    total_ordered: float,
    total_delivered: float,
) -> float:
    if total_ordered <= 0:
        return 0.0
    return min(100.0, round((total_delivered / total_ordered) * 100, 2))


def _create_order_with_lines(
    db: Session,
    supplier_name: str | None,
    order_date: date | None,
    invoice_number: str | None,
    requester_user_id: int | None,
    lines: list[tuple[str, float]],
) -> PurchaseOrder:
    for attempt in range(MAX_ORDER_NUMBER_RETRIES):
        order_number = _get_next_order_number(db, order_date)
        order = PurchaseOrder(
            order_number=order_number,
            supplier_name=supplier_name,
            order_date=order_date,
            requester_user_id=requester_user_id,
            invoice_number=invoice_number,
            status="APERTO",
        )
        db.add(order)
        try:
            db.flush()
        except IntegrityError:
            logger.warning(
                "Duplicate order_number %s on attempt %s",
                order_number,
                attempt + 1,
            )
            db.rollback()
            continue

        for description, qty in lines:
            db.add(
                PurchaseOrderLine(
                    order_id=order.id,
                    description=description,
                    qty_ordered=qty,
                )
            )

        try:
            db.commit()
        except IntegrityError:
            logger.warning(
                "IntegrityError while committing order_number %s on attempt %s",
                order_number,
                attempt + 1,
            )
            db.rollback()
            continue
        return order

    raise HTTPException(
        status_code=500,
        detail="Impossibile generare un numero ordine univoco",
    )


@router.get(
    "/manager/ordini/nuovo",
    response_class=HTMLResponse,
    name="manager_ordini_new",
)
def manager_ordini_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    return render_template(
        templates,
        request,
        "manager/ordini/ordini_new.html",
        {},
        db,
        current_user,
    )


@router.post(
    "/manager/ordini/nuovo",
    response_class=HTMLResponse,
    name="manager_ordini_create",
)
def manager_ordini_create(
    request: Request,
    supplier_name: str = Form(...),
    order_date: str = Form(""),
    invoice_number: str = Form(""),
    description: list[str] = Form(...),
    qty_ordered: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    parsed_order_date = _parse_date(order_date)
    if order_date and parsed_order_date is None:
        raise HTTPException(status_code=400, detail="Data ordine non valida")

    supplier_name_clean = supplier_name.strip()
    if not supplier_name_clean:
        raise HTTPException(status_code=400, detail="Fornitore obbligatorio")

    lines: list[tuple[str, float]] = []
    for raw_description, raw_qty in zip(description, qty_ordered):
        if not raw_description and not raw_qty:
            continue
        parsed_qty = _parse_float(raw_qty)
        if parsed_qty is None or parsed_qty <= 0:
            raise HTTPException(status_code=400, detail="Quantità non valida")
        description_clean = raw_description.strip()
        if not description_clean:
            raise HTTPException(status_code=400, detail="Descrizione mancante")
        lines.append((description_clean, parsed_qty))

    if not lines:
        raise HTTPException(status_code=400, detail="Nessuna riga valida")

    _create_order_with_lines(
        db,
        supplier_name=supplier_name_clean,
        order_date=parsed_order_date,
        invoice_number=invoice_number.strip() or None,
        requester_user_id=current_user.id,
        lines=lines,
    )

    return RedirectResponse(
        url=request.url_for("manager_ordini_new"),
        status_code=303,
    )


@router.get(
    "/manager/ordini",
    response_class=HTMLResponse,
    name="manager_ordini_list",
)
def manager_ordini_list(
    request: Request,
    status: str | None = None,
    supplier: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    normalized_status = (status or "").strip().lower() or None
    supplier_filter = (supplier or "").strip() or None
    parsed_date_from = _parse_date(date_from)
    parsed_date_to = _parse_date(date_to)
    total_orders = db.query(func.count(PurchaseOrder.id)).scalar() or 0
    partial_orders = (
        db.query(func.count(PurchaseOrder.id))
        .filter(func.lower(PurchaseOrder.status) == "parziale")
        .scalar()
        or 0
    )
    closed_orders = (
        db.query(func.count(PurchaseOrder.id))
        .filter(func.lower(PurchaseOrder.status).in_(["chiuso", "completato"]))
        .scalar()
        or 0
    )
    query = db.query(PurchaseOrder)
    if normalized_status:
        query = query.filter(func.lower(PurchaseOrder.status) == normalized_status)
    else:
        query = query.filter(
            or_(
                PurchaseOrder.status.is_(None),
                func.lower(PurchaseOrder.status) != "chiuso",
            )
        )
    if supplier_filter:
        query = query.filter(
            func.lower(PurchaseOrder.supplier_name).contains(
                supplier_filter.lower()
            )
        )
    if parsed_date_from:
        query = query.filter(PurchaseOrder.order_date >= parsed_date_from)
    if parsed_date_to:
        query = query.filter(PurchaseOrder.order_date <= parsed_date_to)
    orders = query.order_by(PurchaseOrder.order_date.desc()).all()
    order_ids = [order.id for order in orders]
    ordered_totals = {}
    delivered_totals = {}
    if order_ids:
        ordered_totals = {
            order_id: total
            for order_id, total in (
                db.query(
                    PurchaseOrderLine.order_id,
                    func.coalesce(func.sum(PurchaseOrderLine.qty_ordered), 0.0),
                )
                .filter(PurchaseOrderLine.order_id.in_(order_ids))
                .group_by(PurchaseOrderLine.order_id)
                .all()
            )
        }
        delivered_totals = {
            order_id: total
            for order_id, total in (
                db.query(
                    PurchaseDelivery.order_id,
                    func.coalesce(func.sum(PurchaseDeliveryLine.qty_delivered), 0.0),
                )
                .join(
                    PurchaseDeliveryLine,
                    PurchaseDeliveryLine.delivery_id == PurchaseDelivery.id,
                )
                .filter(
                    PurchaseDelivery.order_id.in_(order_ids),
                    PurchaseDelivery.confirmed.is_(True),
                )
                .group_by(PurchaseDelivery.order_id)
                .all()
            )
        }
    completion_map = {
        order.id: _calculate_completion_percent(
            ordered_totals.get(order.id, 0.0),
            delivered_totals.get(order.id, 0.0),
        )
        for order in orders
    }
    page_title = "Ordini chiusi" if normalized_status == "chiuso" else "Ordini aperti"
    return render_template(
        templates,
        request,
        "manager/ordini/ordini_list.html",
        {
            "orders": orders,
            "status_filter": normalized_status,
            "supplier_filter": supplier_filter,
            "date_from": parsed_date_from,
            "date_to": parsed_date_to,
            "page_title": page_title,
            "total_orders": total_orders,
            "partial_orders": partial_orders,
            "closed_orders": closed_orders,
            "completion_map": completion_map,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/ordini/chiusi",
    response_class=HTMLResponse,
    name="manager_ordini_list_chiusi",
)
def manager_ordini_list_chiusi(
    request: Request,
    supplier: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    return manager_ordini_list(
        request=request,
        status="chiuso",
        supplier=supplier,
        date_from=date_from,
        date_to=date_to,
        db=db,
        current_user=current_user,
    )


@router.get(
    "/manager/ordini/{order_id}",
    response_class=HTMLResponse,
    name="manager_ordini_detail",
)
def manager_ordini_detail(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    delivered_totals = _load_delivered_totals(db, order.id)
    ordered_total = sum(line.qty_ordered or 0.0 for line in order.lines)
    delivered_total = sum(delivered_totals.get(line.id, 0.0) for line in order.lines)
    completion_percent = _calculate_completion_percent(
        ordered_total, delivered_total
    )

    lines = [
        {
            "id": line.id,
            "description": line.description,
            "qty_ordered": line.qty_ordered,
            "qty_delivered": delivered_totals.get(line.id, 0.0),
            "qty_remaining": max(
                0.0, (line.qty_ordered or 0.0) - delivered_totals.get(line.id, 0.0)
            ),
        }
        for line in order.lines
    ]

    deliveries = (
        db.query(PurchaseDelivery)
        .filter(PurchaseDelivery.order_id == order.id)
        .order_by(PurchaseDelivery.created_at.desc())
        .all()
    )

    return render_template(
        templates,
        request,
        "manager/ordini/ordini_detail.html",
        {
            "order": order,
            "lines": lines,
            "deliveries": deliveries,
            "completion_percent": completion_percent,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/ordini/{order_id}/bolle/nuova",
    response_class=HTMLResponse,
    name="manager_ordini_bolle_nuova",
)
def manager_ordini_bolle_nuova(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    delivered_totals = _load_delivered_totals(db, order.id)
    lines = [
        {
            "id": line.id,
            "description": line.description,
            "qty_ordered": line.qty_ordered,
            "qty_delivered": delivered_totals.get(line.id, 0.0),
            "qty_remaining": max(
                0.0, (line.qty_ordered or 0.0) - delivered_totals.get(line.id, 0.0)
            ),
        }
        for line in order.lines
    ]

    return render_template(
        templates,
        request,
        "manager/ordini/bolla_new.html",
        {
            "order": order,
            "lines": lines,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/ordini/{order_id}/bolle/nuova",
    response_class=HTMLResponse,
    name="manager_ordini_bolle_create",
)
def manager_ordini_bolle_create(
    request: Request,
    order_id: int,
    order_line_id: list[int] = Form(...),
    qty_delivered: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    lines_payload = list(zip(order_line_id, qty_delivered))
    if not lines_payload:
        raise HTTPException(status_code=400, detail="Nessuna riga bolla valida")

    valid_line_ids = {line.id for line in order.lines}
    parsed_lines: list[tuple[int, float]] = []
    for line_id, raw_qty in lines_payload:
        if line_id not in valid_line_ids:
            raise HTTPException(status_code=400, detail="Riga ordine non valida")
        parsed_qty = _parse_float(raw_qty)
        if parsed_qty is None or parsed_qty < 0:
            raise HTTPException(status_code=400, detail="Quantità consegnata non valida")
        if parsed_qty == 0:
            continue
        parsed_lines.append((line_id, parsed_qty))

    if not parsed_lines:
        raise HTTPException(status_code=400, detail="Nessuna quantità consegnata valida")

    delivery_count = (
        db.query(func.count(PurchaseDelivery.id))
        .filter(PurchaseDelivery.order_id == order.id)
        .scalar()
        or 0
    )
    delivery_number = f"{order.order_number}-{delivery_count + 1}"
    delivery = PurchaseDelivery(
        order_id=order.id,
        delivery_number=delivery_number,
        delivery_date=date.today(),
        confirmed=False,
    )
    db.add(delivery)
    db.flush()

    for line_id, parsed_qty in parsed_lines:
        db.add(
            PurchaseDeliveryLine(
                delivery_id=delivery.id,
                order_line_id=line_id,
                qty_delivered=parsed_qty,
            )
        )

    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_ordini_detail", order_id=order.id),
        status_code=303,
    )


@router.post(
    "/manager/ordini/bolle/{delivery_id}/conferma",
    name="manager_ordini_bolle_conferma",
)
def manager_ordini_bolle_conferma(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    delivery = (
        db.query(PurchaseDelivery).filter(PurchaseDelivery.id == delivery_id).first()
    )
    if not delivery:
        raise HTTPException(status_code=404, detail="Bolla non trovata")

    if not delivery.confirmed:
        delivery.confirmed = True
        db.add(delivery)
        db.flush()

    order = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.id == delivery.order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    existing_movimento = (
        db.query(MagazzinoMovimento.id)
        .filter(MagazzinoMovimento.purchase_delivery_id == delivery.id)
        .first()
    )
    if not existing_movimento:
        for line in delivery.lines:
            qty = line.qty_delivered or 0.0
            if qty <= 0:
                continue
            item = _find_magazzino_item_by_description(db, line.order_line.description)
            if not item:
                logger.warning(
                    "Nessun articolo magazzino per riga ordine %s (delivery %s)",
                    line.order_line_id,
                    delivery.id,
                )
                continue
            item.quantita_disponibile = (item.quantita_disponibile or 0.0) + qty
            db.add(item)
            db.add(
                MagazzinoMovimento(
                    item_id=item.id,
                    tipo=MagazzinoMovimentoTipoEnum.carico,
                    quantita=qty,
                    creato_da_user_id=current_user.id,
                    purchase_order_id=delivery.order_id,
                    purchase_delivery_id=delivery.id,
                    note=f"Bolla {delivery.delivery_number}",
                )
            )

    delivered_totals = _load_delivered_totals(db, order.id)
    order_lines = order.lines
    if not order_lines:
        order.status = "APERTO"
    else:
        all_delivered = all(
            delivered_totals.get(line.id, 0.0) >= (line.qty_ordered or 0.0)
            for line in order_lines
        )
        any_delivered = any(
            delivered_totals.get(line.id, 0.0) > 0.0 for line in order_lines
        )
        if all_delivered:
            order.status = "CHIUSO"
        elif any_delivered:
            order.status = "PARZIALE"
        else:
            order.status = "APERTO"
    db.add(order)
    db.commit()

    return {"order_id": order.id, "status": order.status}
