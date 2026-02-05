import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import PurchaseOrder, PurchaseOrderLine, User
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


def _get_next_order_number(db: Session) -> str:
    max_value = (
        db.query(func.max(cast(PurchaseOrder.order_number, Integer))).scalar()
        or 0
    )
    return str(max_value + 1)


def _create_order_with_lines(
    db: Session,
    supplier_name: str | None,
    order_date: date | None,
    invoice_number: str | None,
    requester_user_id: int | None,
    lines: list[tuple[str, float]],
) -> PurchaseOrder:
    for attempt in range(MAX_ORDER_NUMBER_RETRIES):
        order_number = _get_next_order_number(db)
        order = PurchaseOrder(
            order_number=order_number,
            supplier_name=supplier_name,
            order_date=order_date,
            requester_user_id=requester_user_id,
            invoice_number=invoice_number,
            status="NUOVO",
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
