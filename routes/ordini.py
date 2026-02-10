import logging
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import (
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    PurchaseDelivery,
    PurchaseDeliveryLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Site,
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


def _order_destination_label(order: PurchaseOrder) -> str:
    if order.order_kind == "closed":
        site_name = order.site.name if order.site else "-"
        return f"CHIUSO/CANTIERE: {site_name}"
    category_name = order.warehouse_category.nome if order.warehouse_category else "-"
    macro_name = order.warehouse_category.macro if order.warehouse_category else "-"
    return f"MAGAZZINO: {category_name} / {macro_name}"


def _load_order_form_dependencies(db: Session) -> tuple[list[MagazzinoItem], list[Site], list[MagazzinoCategoria], list[User], list[str]]:
    magazzino_items = (
        db.query(MagazzinoItem)
        .filter(MagazzinoItem.attivo.is_(True))
        .order_by(MagazzinoItem.nome.asc())
        .all()
    )
    sites = db.query(Site).filter(Site.is_active.is_(True)).order_by(Site.name.asc()).all()
    warehouse_categories = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.attiva.is_(True))
        .order_by(MagazzinoCategoria.nome.asc())
        .all()
    )
    requesters = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )
    macro_options = sorted({(cat.macro or "Generale").strip() or "Generale" for cat in warehouse_categories})
    if "Generale" not in macro_options:
        macro_options.insert(0, "Generale")
    return magazzino_items, sites, warehouse_categories, requesters, macro_options


def _render_order_form(
    request: Request,
    db: Session,
    current_user: User,
    *,
    error_message: str | None = None,
    form_data: dict | None = None,
):
    magazzino_items, sites, warehouse_categories, requesters, macro_options = _load_order_form_dependencies(db)
    if form_data is None:
        form_data = {
            "supplier_name": "",
            "order_date": "",
            "requester_user_id": str(current_user.id),
            "description_text": "",
            "order_kind": "warehouse",
            "site_id": "",
            "warehouse_category_id": "",
            "new_category_name": "",
            "new_category_macro": "Generale",
            "invoice_number": "",
            "lines": [{"description": "", "qty_ordered": "", "magazzino_item_id": ""}],
        }
    return render_template(
        templates,
        request,
        "manager/ordini/ordini_new.html",
        {
            "magazzino_items": magazzino_items,
            "sites": sites,
            "warehouse_categories": warehouse_categories,
            "requesters": requesters,
            "macro_options": macro_options,
            "error_message": error_message,
            "form_data": form_data,
            "new_category_sentinel": "__new__",
        },
        db,
        current_user,
    )


def _create_order_with_lines(
    db: Session,
    supplier_name: str | None,
    order_date: date | None,
    invoice_number: str | None,
    requester_user_id: int | None,
    lines: list[tuple[str, float, int | None]],
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

        for description, qty, magazzino_item_id in lines:
            db.add(
                PurchaseOrderLine(
                    order_id=order.id,
                    description=description,
                    qty_ordered=qty,
                    magazzino_item_id=magazzino_item_id,
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
    return _render_order_form(request, db, current_user)


@router.post(
    "/manager/ordini/nuovo",
    response_class=HTMLResponse,
    name="manager_ordini_create",
)
def manager_ordini_create(
    request: Request,
    supplier_name: str = Form(...),
    order_date: str = Form(""),
    requester_user_id: str = Form(""),
    description_text: str = Form(""),
    order_kind: str = Form(""),
    site_id: str = Form(""),
    warehouse_category_id: str = Form(""),
    new_category_name: str = Form(""),
    new_category_macro: str = Form(""),
    invoice_number: str = Form(""),
    description: list[str] = Form(...),
    qty_ordered: list[str] = Form(...),
    magazzino_item_id: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    form_data = {
        "supplier_name": supplier_name or "",
        "order_date": order_date or "",
        "requester_user_id": requester_user_id or "",
        "description_text": description_text or "",
        "order_kind": order_kind or "",
        "site_id": site_id or "",
        "warehouse_category_id": warehouse_category_id or "",
        "new_category_name": new_category_name or "",
        "new_category_macro": new_category_macro or "",
        "invoice_number": invoice_number or "",
        "lines": [
            {"description": d or "", "qty_ordered": q or "", "magazzino_item_id": i or ""}
            for d, q, i in zip(description, qty_ordered, magazzino_item_id)
        ],
    }

    parsed_order_date = _parse_date(order_date)
    if not parsed_order_date:
        return _render_order_form(request, db, current_user, error_message="La data ordine è obbligatoria.", form_data=form_data)

    supplier_name_clean = supplier_name.strip()
    if not supplier_name_clean:
        return _render_order_form(request, db, current_user, error_message="Il fornitore è obbligatorio.", form_data=form_data)

    try:
        requester_id_int = int(requester_user_id)
    except (TypeError, ValueError):
        requester_id_int = 0
    requester = db.query(User).filter(User.id == requester_id_int, User.is_active.is_(True)).first()
    if not requester:
        return _render_order_form(request, db, current_user, error_message="Il richiedente è obbligatorio.", form_data=form_data)

    normalized_kind = (order_kind or "").strip().lower()
    if normalized_kind not in {"closed", "warehouse"}:
        return _render_order_form(request, db, current_user, error_message="Il tipo ordine è obbligatorio.", form_data=form_data)

    selected_site_id: int | None = None
    selected_category_id: int | None = None
    if normalized_kind == "closed":
        try:
            selected_site_id = int(site_id)
        except (TypeError, ValueError):
            selected_site_id = None
        site = db.query(Site).filter(Site.id == selected_site_id, Site.is_active.is_(True)).first() if selected_site_id else None
        if not site:
            return _render_order_form(request, db, current_user, error_message="Per ordine chiuso devi selezionare un cantiere valido.", form_data=form_data)
        form_data["warehouse_category_id"] = ""
    else:
        if warehouse_category_id == "__new__":
            nome_categoria = (new_category_name or "").strip()
            macro_categoria = (new_category_macro or "").strip()
            if not nome_categoria:
                return _render_order_form(request, db, current_user, error_message="Inserisci il nome della nuova categoria.", form_data=form_data)
            if not macro_categoria:
                return _render_order_form(request, db, current_user, error_message="Seleziona la macro della nuova categoria.", form_data=form_data)
            existing = db.query(MagazzinoCategoria).filter(func.lower(MagazzinoCategoria.nome) == nome_categoria.lower()).first()
            if existing:
                selected_category_id = existing.id
            else:
                max_order = db.query(func.max(MagazzinoCategoria.ordine)).scalar() or 0
                base_slug = nome_categoria.lower().strip().replace(" ", "-")
                slug = ''.join(ch for ch in base_slug if ch.isalnum() or ch == '-') or 'categoria'
                candidate = slug
                counter = 2
                while db.query(MagazzinoCategoria.id).filter(MagazzinoCategoria.slug == candidate).first():
                    candidate = f"{slug}-{counter}"
                    counter += 1
                categoria = MagazzinoCategoria(
                    nome=nome_categoria,
                    slug=candidate,
                    ordine=max_order + 1,
                    attiva=True,
                    macro=macro_categoria,
                )
                db.add(categoria)
                db.commit()
                db.refresh(categoria)
                selected_category_id = categoria.id
            form_data["warehouse_category_id"] = str(selected_category_id)
        else:
            try:
                selected_category_id = int(warehouse_category_id)
            except (TypeError, ValueError):
                selected_category_id = None
        categoria = db.query(MagazzinoCategoria).filter(MagazzinoCategoria.id == selected_category_id, MagazzinoCategoria.attiva.is_(True)).first() if selected_category_id else None
        if not categoria:
            db.rollback()
            return _render_order_form(request, db, current_user, error_message="Per ordine magazzino devi selezionare una categoria valida.", form_data=form_data)
        form_data["site_id"] = ""

    if len(description) != len(qty_ordered) or len(description) != len(magazzino_item_id):
        db.rollback()
        return _render_order_form(request, db, current_user, error_message="Righe ordine non valide.", form_data=form_data)

    selected_item_ids: set[int] = set()
    for raw_id in magazzino_item_id:
        if raw_id:
            try:
                selected_item_ids.add(int(raw_id))
            except ValueError:
                db.rollback()
                return _render_order_form(request, db, current_user, error_message="Articolo magazzino non valido.", form_data=form_data)

    if selected_item_ids:
        existing_item_ids = {
            item_id
            for (item_id,) in db.query(MagazzinoItem.id)
            .filter(MagazzinoItem.id.in_(selected_item_ids))
            .all()
        }
        if selected_item_ids - existing_item_ids:
            db.rollback()
            return _render_order_form(request, db, current_user, error_message="Uno o più articoli magazzino non sono validi.", form_data=form_data)

    lines: list[tuple[str, float, int | None]] = []
    for raw_description, raw_qty, raw_item_id in zip(description, qty_ordered, magazzino_item_id):
        if not raw_description and not raw_qty:
            continue
        parsed_qty = _parse_float(raw_qty)
        if parsed_qty is None or parsed_qty <= 0:
            db.rollback()
            return _render_order_form(request, db, current_user, error_message="Quantità non valida nelle righe ordine.", form_data=form_data)
        description_clean = (raw_description or "").strip()
        if not description_clean:
            db.rollback()
            return _render_order_form(request, db, current_user, error_message="Descrizione riga mancante.", form_data=form_data)
        item_id = int(raw_item_id) if raw_item_id else None
        lines.append((description_clean, parsed_qty, item_id))

    if not lines:
        db.rollback()
        return _render_order_form(request, db, current_user, error_message="Inserisci almeno una riga ordine valida.", form_data=form_data)

    try:
        order = _create_order_with_lines(
            db,
            supplier_name=supplier_name_clean,
            order_date=parsed_order_date,
            invoice_number=invoice_number.strip() or None,
            requester_user_id=requester.id,
            lines=lines,
        )
        order.description = (description_text or "").strip() or None
        order.order_kind = normalized_kind
        order.site_id = selected_site_id if normalized_kind == "closed" else None
        order.warehouse_category_id = selected_category_id if normalized_kind == "warehouse" else None
        db.add(order)
        db.commit()
    except Exception:
        db.rollback()
        raise

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
    destination_map = {order.id: _order_destination_label(order) for order in orders}
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
            "destination_map": destination_map,
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
    error_message = request.query_params.get("err")

    return render_template(
        templates,
        request,
        "manager/ordini/ordini_detail.html",
        {
            "order": order,
            "lines": lines,
            "deliveries": deliveries,
            "completion_percent": completion_percent,
            "error_message": error_message,
            "destination_label": _order_destination_label(order),
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
    request: Request,
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

    order = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.id == delivery.order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    missing_line = next(
        (
            line
            for line in delivery.lines
            if line.order_line and line.order_line.magazzino_item_id is None
        ),
        None,
    )
    if missing_line:
        message = (
            "Impossibile confermare: associa un articolo di magazzino alla "
            f"riga ordine {missing_line.order_line_id}"
        )
        query_string = urlencode({"err": message})
        url = f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
        return RedirectResponse(url=url, status_code=303)

    existing_movimento = (
        db.query(MagazzinoMovimento.id)
        .filter(MagazzinoMovimento.purchase_delivery_id == delivery.id)
        .first()
    )
    if not existing_movimento:
        if not delivery.confirmed:
            delivery.confirmed = True
            db.add(delivery)
            db.flush()
        for line in delivery.lines:
            qty = line.qty_delivered or 0.0
            if qty <= 0:
                continue
            item = (
                db.query(MagazzinoItem)
                .filter(MagazzinoItem.id == line.order_line.magazzino_item_id)
                .first()
            )
            if not item:
                raise HTTPException(
                    status_code=400, detail="Articolo magazzino non valido"
                )
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
    elif not delivery.confirmed:
        delivery.confirmed = True
        db.add(delivery)

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

    return RedirectResponse(
        url=request.url_for("manager_ordini_detail", order_id=order.id),
        status_code=303,
    )
