import logging
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import date, datetime
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import (
    SupplierArticle,
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMacro,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    DeliveryTypeEnum,
    PurchaseDelivery,
    PurchaseDeliveryLine,
    PurchaseOrder,
    Depot,
    PurchaseOrderLine,
    Site,
    Supplier,
    User,
)
from permissions import has_perm
from template_context import register_manager_badges, render_template
from utils.places import DEFAULT_DEPOT_NAMES

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["ordini"])
logger = logging.getLogger("lenta_france_gestionale.errors")

INVOICE_UPLOAD_DIR = Path("static/uploads/invoices")


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id or "unknown"


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


def _orders_navigation_counts(db: Session) -> dict[str, int]:
    ordini_aperti_count = (
        db.query(func.count(PurchaseOrder.id))
        .filter(
            or_(
                PurchaseOrder.status.is_(None),
                ~func.lower(PurchaseOrder.status).in_(["chiuso", "completato"]),
            )
        )
        .scalar()
        or 0
    )
    ordini_chiusi_count = (
        db.query(func.count(PurchaseOrder.id))
        .filter(func.lower(PurchaseOrder.status).in_(["chiuso", "completato"]))
        .scalar()
        or 0
    )
    magazzino_count = db.query(func.count(MagazzinoItem.id)).scalar() or 0
    return {
        "ordini_aperti_count": ordini_aperti_count,
        "ordini_chiusi_count": ordini_chiusi_count,
        "magazzino_count": magazzino_count,
    }


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


def _get_next_delivery_number(db: Session, order: PurchaseOrder) -> str:
    delivery_count = (
        db.query(func.count(PurchaseDelivery.id))
        .filter(PurchaseDelivery.order_id == order.id)
        .scalar()
        or 0
    )
    return f"{order.order_number}-{delivery_count + 1}"


def _build_delivery_lines(order: PurchaseOrder, delivered_totals: dict[int, float]) -> list[dict]:
    return [
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


def _render_bolla_form(
    request: Request,
    db: Session,
    current_user: User,
    *,
    order: PurchaseOrder,
    error_message: str | None = None,
    form_data: dict | None = None,
):
    delivered_totals = _load_delivered_totals(db, order.id)
    lines = _build_delivery_lines(order, delivered_totals)
    if form_data is None:
        form_data = {
            "delivery_number": _get_next_delivery_number(db, order),
        }

    return render_template(
        templates,
        request,
        "manager/ordini/bolla_new.html",
        {
            "order": order,
            "lines": lines,
            "error_message": error_message,
            "form_data": form_data,
        },
        db,
        current_user,
    )


def _collect_pending_discharge_requirements(
    db: Session, order: PurchaseOrder
) -> tuple[dict[int, float], list[PurchaseDelivery]]:
    confirmed_deliveries = (
        db.query(PurchaseDelivery)
        .filter(
            PurchaseDelivery.order_id == order.id,
            PurchaseDelivery.confirmed.is_(True),
        )
        .order_by(PurchaseDelivery.created_at.asc())
        .all()
    )
    if not confirmed_deliveries:
        return {}, []

    confirmed_delivery_ids = [delivery.id for delivery in confirmed_deliveries]
    discharged_delivery_ids = {
        delivery_id
        for (delivery_id,) in db.query(MagazzinoMovimento.purchase_delivery_id)
        .filter(
            MagazzinoMovimento.purchase_order_id == order.id,
            MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
            MagazzinoMovimento.purchase_delivery_id.in_(confirmed_delivery_ids),
        )
        .all()
        if delivery_id is not None
    }

    pending_deliveries = [
        delivery
        for delivery in confirmed_deliveries
        if delivery.id not in discharged_delivery_ids
    ]

    required_by_item: dict[int, float] = {}
    for delivery in pending_deliveries:
        for line in delivery.lines:
            if not line.order_line or line.qty_delivered is None or line.qty_delivered <= 0:
                continue
            item_id = line.order_line.magazzino_item_id
            if item_id is None:
                continue
            required_by_item[item_id] = required_by_item.get(item_id, 0.0) + line.qty_delivered

    return required_by_item, pending_deliveries


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
    macro_name = (
        order.warehouse_category.macro.name
        if order.warehouse_category and order.warehouse_category.macro
        else "-"
    )
    return f"MAGAZZINO: {macro_name} → {category_name}"


def _order_supplier_label(order: PurchaseOrder) -> str:
    if order.supplier and order.supplier.name:
        return order.supplier.name
    if order.supplier_name:
        return order.supplier_name
    return "-"


def _order_email_recipient(order: PurchaseOrder) -> str:
    return (
        order.contact_email_override
        or (order.supplier.contact_email if order.supplier and order.supplier.contact_email else "")
        or (order.supplier.email if order.supplier and order.supplier.email else "")
        or ""
    ).strip()


def _order_email_contact_name(order: PurchaseOrder) -> str | None:
    return (
        order.contact_name_override
        or (order.supplier.contact_name if order.supplier and order.supplier.contact_name else "")
        or None
    )



def build_delivery_label(
    lang: str,
    delivery_type: str,
    site: Site | None = None,
    depot: Depot | None = None,
) -> tuple[str, str]:
    normalized_lang = (lang or "it").strip().lower()
    if normalized_lang not in {"it", "fr"}:
        normalized_lang = "it"

    normalized_type = (delivery_type or DeliveryTypeEnum.PICKUP.value).strip().upper()
    address = ""
    label = ""

    if normalized_type == DeliveryTypeEnum.DEPOT.value:
        depot_name = depot.name if depot and depot.name else "-"
        label = f"Dépôt : {depot_name}" if normalized_lang == "fr" else f"Deposito: {depot_name}"
        address = _format_depot_full_address(depot) if depot else ""
        return label, address

    if normalized_type == DeliveryTypeEnum.SITE.value:
        site_name = site.name if site and site.name else "-"
        label = f"Chantier : {site_name}" if normalized_lang == "fr" else f"Cantiere: {site_name}"
        address = (site.address or "").strip() if site and site.address else ""
        return label, address

    label = "Enlèvement chez le fournisseur" if normalized_lang == "fr" else "Ritiro dal fornitore"
    return label, ""


def _format_depot_full_address(depot: Depot | None) -> str:
    if not depot:
        return ""
    parts = [
        (depot.address or "").strip(),
        " ".join(part for part in [
            (depot.zip_code or "").strip(),
            (depot.city or "").strip(),
        ] if part).strip(),
        (depot.province or "").strip(),
        (depot.country or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def _format_qty(value: float | int | None) -> str:
    if value is None:
        return "0"
    as_float = float(value)
    if as_float.is_integer():
        return str(int(as_float))
    return f"{as_float:.2f}".rstrip("0").rstrip(".")


def fix_mojibake(text: str) -> str:
    if not text:
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


def build_order_email(
    order: PurchaseOrder,
    supplier: Supplier | None,
    lang: str,
    delivery_type: str | None = None,
    delivery_site_id: int | None = None,
    delivery_depot_id: int | None = None,
) -> tuple[str, str]:
    normalized_lang = (lang or "it").strip().lower()
    if normalized_lang not in {"it", "fr"}:
        normalized_lang = "it"

    resolved_supplier = supplier or order.supplier
    supplier_name = (
        (resolved_supplier.name if resolved_supplier and resolved_supplier.name else "")
        or _order_supplier_label(order)
    )
    contact_name = (
        (order.contact_name_override or "").strip()
        or (order.contact_name or "").strip()
        or ((resolved_supplier.contact_name or "").strip() if resolved_supplier else "")
    )
    resolved_site = order.delivery_site
    resolved_depot = order.delivery_depot

    if delivery_site_id and resolved_site and resolved_site.id != delivery_site_id:
        resolved_site = None
    if delivery_depot_id and resolved_depot and resolved_depot.id != delivery_depot_id:
        resolved_depot = None

    normalized_delivery_type = (delivery_type or order.delivery_type or DeliveryTypeEnum.PICKUP.value).strip().upper()
    destination_label, destination_address = build_delivery_label(
        normalized_lang,
        normalized_delivery_type,
        site=resolved_site,
        depot=resolved_depot,
    )
    order_number = order.order_number or str(order.id or "-")
    order_date_text = order.order_date.strftime("%d/%m/%Y") if order.order_date else "-"
    lines = [
        f"- {(line.description or '-').strip() or '-'}: {_format_qty(line.qty_ordered)}"
        for line in order.lines
    ]

    if normalized_lang == "fr":
        subject = f"Commande n° {order_number} - {supplier_name} · {destination_label}"
        greeting = f"Bonjour {contact_name}," if contact_name else "Bonjour,"
        body_parts = [
            greeting,
            "",
            f"Nous vous transmettons notre commande n° {order_number} du {order_date_text}.",
            f"Lieu de livraison : {destination_label}.",
        ]
        if destination_address:
            body_parts.append(f"Adresse : {destination_address}.")
        body_parts.extend(
            [
                "",
                "Détail des lignes de commande :",
                "",
                *[line.replace(":", " - Quantité:") for line in (lines or ["-"])],
                "",
                "Merci de confirmer la prise en charge et de nous indiquer vos délais de livraison.",
                "",
                "Cordialement,",
                "Lenta France",
            ]
        )
        body = "\n".join(body_parts)
    else:
        subject = f"Ordine n. {order_number} - {supplier_name} · {destination_label}"
        greeting = f"Gentile {contact_name}," if contact_name else "Gentili,"
        body_parts = [
            greeting,
            "",
            f"Vi trasmettiamo il nostro ordine n. {order_number} del {order_date_text}.",
            f"Consegna: {destination_label}.",
        ]
        if destination_address:
            body_parts.append(f"Indirizzo: {destination_address}.")
        body_parts.extend(
            [
                "",
                "Riepilogo righe ordine:",
                "",
                *[line.replace(":", " - Quantità:") for line in (lines or ["-"])],
                "",
                "Vi chiediamo conferma di presa in carico e indicazione dei tempi di consegna.",
                "",
                "Cordiali saluti,",
                "Lenta France",
            ]
        )
        body = "\n".join(body_parts)

    subject = fix_mojibake(subject)
    body = fix_mojibake(body)
    return subject, body


def _compose_depot_full_address(depot: Depot | None) -> str:
    if not depot:
        return ""
    parts = [
        (depot.address or "").strip(),
        (depot.zip_code or "").strip(),
        (depot.city or "").strip(),
        (depot.province or "").strip(),
        (depot.country or "").strip(),
    ]
    return ", ".join([part for part in parts if part])


def build_order_mailto_link(order: PurchaseOrder, lang: str = "it") -> str:
    subject, body = build_order_email(order, supplier=order.supplier, lang=lang)
    recipient_email = _order_email_recipient(order)
    subject_encoded = quote(subject.encode("cp1252"), safe="")
    body_encoded = quote(body.encode("cp1252"), safe="")
    return f"mailto:{recipient_email}?subject={subject_encoded}&body={body_encoded}"



def _group_warehouse_categories_by_macro(
    warehouse_categories: list[MagazzinoCategoria],
) -> list[dict[str, object]]:
    grouped: dict[str, list[MagazzinoCategoria]] = {}
    for category in warehouse_categories:
        macro_name = (
            category.macro.name
            if category.macro and category.macro.name
            else "Senza macro"
        )
        grouped.setdefault(macro_name, []).append(category)

    ordered_groups: list[dict[str, object]] = []
    for macro_name in sorted(grouped.keys(), key=lambda value: value.lower()):
        categories = sorted(grouped[macro_name], key=lambda c: ((c.ordine or 0), c.nome.lower()))
        ordered_groups.append({"macro_name": macro_name, "categories": categories})
    return ordered_groups


def _load_order_form_dependencies(db: Session) -> tuple[list[MagazzinoItem], list[Site], list[MagazzinoCategoria], list[User], list[MagazzinoMacro], list[Supplier], list[Depot]]:
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
        .order_by(
            MagazzinoCategoria.macro_id.asc(),
            MagazzinoCategoria.ordine.asc(),
            MagazzinoCategoria.nome.asc(),
        )
        .all()
    )
    requesters = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.full_name.asc(), User.email.asc())
        .all()
    )
    macros = db.query(MagazzinoMacro).order_by(MagazzinoMacro.ordine.asc(), MagazzinoMacro.name.asc()).all()
    suppliers = db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name.asc(), Supplier.id.asc()).all()
    depots = db.query(Depot).filter(Depot.is_active.is_(True)).filter(func.lower(func.trim(Depot.name)).notin_(DEFAULT_DEPOT_NAMES)).order_by(Depot.name.asc()).all()
    return magazzino_items, sites, warehouse_categories, requesters, macros, suppliers, depots


def _render_order_form(
    request: Request,
    db: Session,
    current_user: User,
    *,
    error_message: str | None = None,
    form_data: dict | None = None,
):
    magazzino_items, sites, warehouse_categories, requesters, macros, suppliers, depots = _load_order_form_dependencies(db)
    grouped_warehouse_categories = _group_warehouse_categories_by_macro(warehouse_categories)
    if form_data is None:
        form_data = {
            "supplier_id": "",
            "contact_name_override": "",
            "contact_email_override": "",
            "order_date": "",
            "requester_user_id": str(current_user.id),
            "description_text": "",
            "order_kind": "warehouse",
            "site_id": "",
            "warehouse_category_id": "",
            "new_category_name": "",
            "category_mode": "existing",
            "macro_id": "",
            "macro": "",
            "new_macro_name": "",
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
            "grouped_warehouse_categories": grouped_warehouse_categories,
            "requesters": requesters,
            "macros": macros,
            "suppliers": suppliers,
            "depots": depots,
            "error_message": error_message,
            "form_data": form_data,
            "new_category_sentinel": "__new__",
            "new_macro_sentinel": "__new__",
        },
        db,
        current_user,
    )


def _create_order_with_lines(
    db: Session,
    supplier_name: str | None,
    supplier_id: int | None,
    order_date: date | None,
    requester_user_id: int | None,
    lines: list[tuple[str, float, int | None]],
) -> PurchaseOrder:
    order = PurchaseOrder(
        order_number=_get_next_order_number(db, order_date),
        supplier_name=supplier_name,
        supplier_id=supplier_id,
        order_date=order_date,
        requester_user_id=requester_user_id,
        status="APERTO",
    )
    db.add(order)
    db.flush()

    for description, qty, magazzino_item_id in lines:
        db.add(
            PurchaseOrderLine(
                order_id=order.id,
                description=description,
                qty_ordered=qty,
                magazzino_item_id=magazzino_item_id,
            )
        )

    return order


def _get_or_create_warehouse_item(
    db: Session,
    *,
    categoria_id: int,
    nome_item: str,
) -> MagazzinoItem:
    normalized_name = nome_item.strip()
    existing_item = (
        db.query(MagazzinoItem)
        .filter(
            MagazzinoItem.categoria_id == categoria_id,
            func.lower(MagazzinoItem.nome) == normalized_name.lower(),
        )
        .first()
    )
    if existing_item:
        return existing_item

    new_item = MagazzinoItem(
        nome=normalized_name,
        categoria_id=categoria_id,
        quantita_disponibile=0.0,
        attivo=True,
    )
    db.add(new_item)
    db.flush()
    return new_item


def _build_unique_category_slug(db: Session, category_name: str) -> str:
    base_slug = category_name.lower().strip().replace(" ", "-")
    slug = "".join(ch for ch in base_slug if ch.isalnum() or ch == "-") or "categoria"
    candidate = slug
    counter = 2
    while db.query(MagazzinoCategoria.id).filter(MagazzinoCategoria.slug == candidate).first():
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


def _get_or_create_macro(
    db: Session,
    *,
    macro_value: str,
    new_macro_name: str,
) -> MagazzinoMacro:
    if macro_value == "__new__":
        if not new_macro_name:
            raise HTTPException(status_code=400, detail="Nome nuova macro obbligatorio.")
        selected_macro = (
            db.query(MagazzinoMacro)
            .filter(func.lower(MagazzinoMacro.name) == new_macro_name.lower())
            .first()
        )
        if selected_macro:
            return selected_macro

        selected_macro = MagazzinoMacro(name=new_macro_name)
        db.add(selected_macro)
        db.flush()
        return selected_macro

    try:
        macro_id_int = int(macro_value)
    except (TypeError, ValueError):
        macro_id_int = 0
    selected_macro = db.query(MagazzinoMacro).filter(MagazzinoMacro.id == macro_id_int).first()
    if not selected_macro:
        raise HTTPException(status_code=400, detail="Macro non valida.")
    return selected_macro


def _get_or_create_category_for_macro(
    db: Session,
    *,
    selected_macro: MagazzinoMacro,
) -> MagazzinoCategoria:
    return _get_or_create_category_for_name(
        db,
        category_name=selected_macro.name,
        selected_macro=selected_macro,
    )


def _get_or_create_category_for_name(
    db: Session,
    *,
    category_name: str,
    selected_macro: MagazzinoMacro,
) -> MagazzinoCategoria:
    normalized_name = category_name.strip()
    macro_name = (selected_macro.name or "").strip()
    if macro_name and normalized_name.lower().startswith(macro_name.lower()):
        remainder = normalized_name[len(macro_name):].strip(" -_/→")
        if remainder:
            normalized_name = remainder
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Nome categoria non valido.")

    existing_category = (
        db.query(MagazzinoCategoria)
        .filter(func.lower(MagazzinoCategoria.nome) == normalized_name.lower())
        .first()
    )
    if existing_category:
        return existing_category

    max_order = db.query(func.max(MagazzinoCategoria.ordine)).scalar() or 0
    categoria = MagazzinoCategoria(
        nome=normalized_name,
        slug=_build_unique_category_slug(db, normalized_name),
        ordine=max_order + 1,
        attiva=True,
        macro_id=selected_macro.id,
        icon=selected_macro.icon,
        color=selected_macro.color,
    )
    db.add(categoria)
    db.flush()
    return categoria


@router.post(
    "/api/ordini/ensure-warehouse-item",
    name="api_ordini_ensure_warehouse_item",
)
def api_ordini_ensure_warehouse_item(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    macro_value = str((payload.get("macro_id") or "").strip())
    new_macro_name = (payload.get("new_macro_name") or "").strip()
    item_name = (payload.get("item_name") or "").strip()

    if not item_name:
        raise HTTPException(status_code=400, detail="Nome articolo obbligatorio.")

    try:
        selected_macro = _get_or_create_macro(
            db,
            macro_value=macro_value,
            new_macro_name=new_macro_name,
        )
        categoria = _get_or_create_category_for_macro(
            db,
            selected_macro=selected_macro,
        )
        item = _get_or_create_warehouse_item(
            db,
            categoria_id=categoria.id,
            nome_item=item_name,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Impossibile creare categoria o articolo.")
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "categoria_id": categoria.id,
        "categoria_nome": categoria.nome,
        "macro_id": selected_macro.id,
        "macro_nome": selected_macro.name,
        "item_id": item.id,
        "item_nome": item.nome,
    }


@router.post(
    "/api/macros",
    name="api_macros_create",
)
def api_macros_create(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    name = (payload.get("name") or "").strip()
    _description = (payload.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome macro obbligatorio.")

    existing = db.query(MagazzinoMacro).filter(func.lower(MagazzinoMacro.name) == name.lower()).first()
    if existing:
        return {"id": existing.id, "name": existing.name}

    macro = MagazzinoMacro(name=name)
    db.add(macro)
    db.commit()
    db.refresh(macro)
    return {"id": macro.id, "name": macro.name}


@router.post(
    "/api/tipologie",
    name="api_tipologie_create",
)
def api_tipologie_create(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    name = (payload.get("name") or "").strip()
    _description = (payload.get("description") or "").strip()
    macro_id_raw = str((payload.get("macro_id") or "").strip())

    if not name:
        raise HTTPException(status_code=400, detail="Nome tipologia obbligatorio.")
    try:
        macro_id = int(macro_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Macro non valida.")

    macro = db.query(MagazzinoMacro).filter(MagazzinoMacro.id == macro_id).first()
    if not macro:
        raise HTTPException(status_code=400, detail="Macro non valida.")

    categoria = _get_or_create_category_for_name(
        db,
        category_name=name,
        selected_macro=macro,
    )
    db.commit()
    db.refresh(categoria)

    return {"id": categoria.id, "name": categoria.nome, "macro_id": categoria.macro_id}


@router.get(
    "/manager/fornitori",
    response_class=HTMLResponse,
    name="manager_fornitori_list",
)
def manager_fornitori_list(
    request: Request,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    query_text = (q or "").strip()
    supplier_query = db.query(Supplier)
    if query_text:
        supplier_query = supplier_query.filter(
            or_(
                func.lower(Supplier.name).contains(query_text.lower()),
                func.lower(Supplier.email).contains(query_text.lower()),
            )
        )
    suppliers = supplier_query.order_by(Supplier.updated_at.desc(), Supplier.id.desc()).all()
    return render_template(
        templates,
        request,
        "manager/fornitori/list.html",
        {"suppliers": suppliers, "q": query_text},
        db,
        current_user,
    )


@router.get(
    "/manager/fornitori/nuovo",
    response_class=HTMLResponse,
    name="manager_fornitori_new",
)
def manager_fornitori_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    return render_template(
        templates,
        request,
        "manager/fornitori/form.html",
        {
            "supplier": None,
            "form_action": request.url_for("manager_fornitori_create"),
            "error_message": None,
            "is_new": True,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/fornitori/nuovo",
    response_class=HTMLResponse,
    name="manager_fornitori_create",
)
def manager_fornitori_create(
    request: Request,
    name: str = Form(""),
    city: str = Form(""),
    address: str = Form(""),
    zip_code: str = Form(""),
    province: str = Form(""),
    country: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    vat_number: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier = Supplier(
        name=name.strip() or None,
        city=city.strip() or None,
        address=address.strip() or None,
        zip_code=zip_code.strip() or None,
        province=province.strip() or None,
        country=country.strip() or None,
        email=email.strip() or None,
        phone=phone.strip() or None,
        vat_number=vat_number.strip() or None,
        notes=notes.strip() or None,
        is_active=True,
    )
    db.add(supplier)
    db.commit()
    return RedirectResponse(url=request.url_for("manager_fornitori_list"), status_code=303)


@router.get(
    "/manager/fornitori/{supplier_id}",
    response_class=HTMLResponse,
    name="manager_fornitori_edit",
)
def manager_fornitori_edit(
    request: Request,
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    return render_template(
        templates,
        request,
        "manager/fornitori/form.html",
        {
            "supplier": supplier,
            "form_action": request.url_for("manager_fornitori_save", supplier_id=supplier.id),
            "error_message": None,
            "is_new": False,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/fornitori/{supplier_id}",
    response_class=HTMLResponse,
    name="manager_fornitori_save",
)
def manager_fornitori_save(
    request: Request,
    supplier_id: int,
    name: str = Form(""),
    city: str = Form(""),
    address: str = Form(""),
    zip_code: str = Form(""),
    province: str = Form(""),
    country: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    vat_number: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    supplier.name = name.strip() or None
    supplier.city = city.strip() or None
    supplier.address = address.strip() or None
    supplier.zip_code = zip_code.strip() or None
    supplier.province = province.strip() or None
    supplier.country = country.strip() or None
    supplier.email = email.strip() or None
    supplier.phone = phone.strip() or None
    supplier.vat_number = vat_number.strip() or None
    supplier.notes = notes.strip() or None
    db.commit()
    return RedirectResponse(url=request.url_for("manager_fornitori_list"), status_code=303)


@router.post(
    "/manager/fornitori/{supplier_id}/toggle",
    name="manager_fornitori_toggle",
)
def manager_fornitori_toggle(
    request: Request,
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    supplier.is_active = not bool(supplier.is_active)
    db.commit()
    return RedirectResponse(url=request.url_for("manager_fornitori_list"), status_code=303)


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


@router.get(
    "/manager/ordini/api/fornitore/{supplier_id}/articoli",
    name="manager_ordini_supplier_articles",
)
def manager_ordini_supplier_articles(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    """Codici articolo salvati per un fornitore (per l'autocompletamento)."""
    _ensure_manager(current_user)
    articoli = (
        db.query(SupplierArticle)
        .filter(SupplierArticle.supplier_id == supplier_id)
        .order_by(SupplierArticle.codice.asc())
        .all()
    )
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "articoli": [
            {"codice": a.codice, "descrizione": a.descrizione or "", "unita": a.unita or "",
             "ultimo_prezzo": a.ultimo_prezzo}
            for a in articoli
        ]
    })


def _apply_line_codes_and_catalog(db, order, line_codes, supplier) -> None:
    """Imposta il codice su ogni riga d'ordine e aggiorna il catalogo del
    fornitore (crea i codici nuovi, aggiorna quelli esistenti)."""
    order_lines = list(order.lines)
    for line, code in zip(order_lines, line_codes):
        if code:
            line.codice = code
    if supplier is None:
        return
    now = datetime.utcnow()
    for line, code in zip(order_lines, line_codes):
        if not code:
            continue
        art = (
            db.query(SupplierArticle)
            .filter(SupplierArticle.supplier_id == supplier.id, SupplierArticle.codice == code)
            .first()
        )
        if art:
            if not art.descrizione and line.description:
                art.descrizione = line.description
            art.last_used_at = now
            art.usi = (art.usi or 0) + 1
        else:
            db.add(SupplierArticle(
                supplier_id=supplier.id, codice=code,
                descrizione=line.description, last_used_at=now, usi=1,
            ))


@router.post(
    "/manager/ordini/nuovo",
    response_class=HTMLResponse,
    name="manager_ordini_create",
)
def manager_ordini_create(
    request: Request,
    supplier_id: str = Form(""),
    supplier_name: str = Form(""),
    new_supplier_name: str = Form(""),
    new_supplier_email: str = Form(""),
    new_supplier_phone: str = Form(""),
    contact_name_override: str = Form(""),
    contact_email_override: str = Form(""),
    order_date: str = Form(""),
    requester_user_id: str = Form(""),
    description_text: str = Form(""),
    order_kind: str = Form(""),
    site_id: str = Form(""),
    warehouse_category_id: str = Form(""),
    new_category_name: str = Form(""),
    category_mode: str = Form("existing"),
    macro_id: str = Form(""),
    macro: str = Form(""),
    new_category_macro_id: str = Form(""),
    new_macro_name: str = Form(""),
    description: list[str] = Form(...),
    qty_ordered: list[str] = Form(...),
    magazzino_item_id: list[str] = Form(...),
    codice: list[str] = Form([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    form_data = {
        "supplier_id": supplier_id or "",
        "supplier_name": supplier_name or "",
        "new_supplier_name": new_supplier_name or "",
        "new_supplier_email": new_supplier_email or "",
        "new_supplier_phone": new_supplier_phone or "",
        "contact_name_override": contact_name_override or "",
        "contact_email_override": contact_email_override or "",
        "order_date": order_date or "",
        "requester_user_id": requester_user_id or "",
        "description_text": description_text or "",
        "order_kind": order_kind or "",
        "site_id": site_id or "",
        "warehouse_category_id": warehouse_category_id or "",
        "new_category_name": new_category_name or "",
        "category_mode": category_mode or "existing",
        "macro_id": macro_id or new_category_macro_id or "",
        "macro": macro or "",
        "new_macro_name": new_macro_name or "",
        "lines": [
            {"description": d or "", "qty_ordered": q or "", "magazzino_item_id": i or ""}
            for d, q, i in zip(description, qty_ordered, magazzino_item_id)
        ],
    }

    parsed_order_date = _parse_date(order_date)
    if not parsed_order_date:
        return _render_order_form(request, db, current_user, error_message="La data ordine è obbligatoria.", form_data=form_data)

    selected_supplier_id: int | None = None
    selected_supplier: Supplier | None = None
    contact_name_override_clean = (contact_name_override or "").strip() or None
    contact_email_override_clean = (contact_email_override or "").strip() or None

    supplier_id_raw = (supplier_id or "").strip()
    supplier_name_raw = (supplier_name or "").strip()
    if not supplier_id_raw and not supplier_name_raw:
        return _render_order_form(request, db, current_user, error_message="Seleziona un fornitore.", form_data=form_data)

    if supplier_id_raw == "__new__":
        new_supplier = Supplier(
            name=(new_supplier_name or supplier_name or "").strip() or None,
            email=(new_supplier_email or "").strip() or None,
            phone=(new_supplier_phone or "").strip() or None,
            contact_name=None,
            contact_email=None,
            is_active=True,
        )
        db.add(new_supplier)
        db.flush()
        selected_supplier_id = new_supplier.id
        selected_supplier = new_supplier
    elif supplier_id_raw:
        try:
            selected_supplier_id = int(supplier_id_raw)
        except (TypeError, ValueError):
            return _render_order_form(request, db, current_user, error_message="Fornitore non valido.", form_data=form_data)
        supplier = db.query(Supplier).filter(Supplier.id == selected_supplier_id).first()
        if not supplier:
            return _render_order_form(request, db, current_user, error_message="Fornitore non trovato.", form_data=form_data)
        selected_supplier = supplier
    elif supplier_name_raw:
        fallback_supplier = Supplier(
            name=supplier_name_raw or None,
            email=(new_supplier_email or "").strip() or None,
            phone=(new_supplier_phone or "").strip() or None,
            is_active=True,
        )
        db.add(fallback_supplier)
        db.flush()
        selected_supplier_id = fallback_supplier.id
        selected_supplier = fallback_supplier

    if selected_supplier is None:
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
        if category_mode == "new" or warehouse_category_id == "__new__":
            macro_value = (macro_id or macro or new_category_macro_id or "").strip()
            if not macro_value:
                return _render_order_form(request, db, current_user, error_message="Seleziona una macro valida per il nuovo articolo.", form_data=form_data)

            try:
                selected_macro = _get_or_create_macro(
                    db,
                    macro_value=macro_value,
                    new_macro_name=(new_macro_name or "").strip(),
                )
            except HTTPException as exc:
                return _render_order_form(request, db, current_user, error_message=str(exc.detail), form_data=form_data)

            categoria = _get_or_create_category_for_macro(
                db,
                selected_macro=selected_macro,
            )
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
        if macro_id and not (category_mode == "new" or warehouse_category_id == "__new__"):
            try:
                selected_macro_id = int(macro_id)
            except (TypeError, ValueError):
                db.rollback()
                return _render_order_form(request, db, current_user, error_message="Macro non valida.", form_data=form_data)
            if categoria.macro_id and categoria.macro_id != selected_macro_id:
                db.rollback()
                return _render_order_form(request, db, current_user, error_message="La tipologia selezionata non appartiene alla macro scelta.", form_data=form_data)
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

    # Codici articolo per riga (allineati a description/qty), padding se mancanti.
    codici_padded = list(codice) + [""] * max(0, len(description) - len(codice))
    lines: list[tuple[str, float, int | None]] = []
    line_codes: list[str | None] = []
    for raw_description, raw_qty, raw_item_id, raw_codice in zip(description, qty_ordered, magazzino_item_id, codici_padded):
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
        line_codes.append((raw_codice or "").strip() or None)

    if not lines:
        db.rollback()
        return _render_order_form(request, db, current_user, error_message="Inserisci almeno una riga ordine valida.", form_data=form_data)

    is_new_warehouse_category = normalized_kind == "warehouse" and (
        category_mode == "new" or warehouse_category_id == "__new__"
    )
    if is_new_warehouse_category and selected_category_id is not None:
        cached_items_by_name: dict[str, MagazzinoItem] = {}
        updated_lines: list[tuple[str, float, int | None]] = []
        for index, (description_clean, parsed_qty, item_id) in enumerate(lines):
            if item_id is not None:
                updated_lines.append((description_clean, parsed_qty, item_id))
                continue

            cache_key = description_clean.lower()
            selected_item = cached_items_by_name.get(cache_key)
            if selected_item is None:
                selected_item = _get_or_create_warehouse_item(
                    db,
                    categoria_id=selected_category_id,
                    nome_item=description_clean,
                )
                cached_items_by_name[cache_key] = selected_item

            updated_lines.append((description_clean, parsed_qty, selected_item.id))
            if index < len(form_data["lines"]):
                form_data["lines"][index]["magazzino_item_id"] = str(selected_item.id)

        lines = updated_lines

    try:
        order = _create_order_with_lines(
            db,
            supplier_name=selected_supplier.name if selected_supplier and selected_supplier.name else None,
            supplier_id=selected_supplier_id,
            order_date=parsed_order_date,
            requester_user_id=requester.id,
            lines=lines,
        )
        order.description = (description_text or "").strip() or None
        order.supplier_email = None
        order.supplier_phone = None
        order.contact_name = selected_supplier.contact_name if selected_supplier else None
        order.recipient_email = selected_supplier.contact_email if selected_supplier and selected_supplier.contact_email else (selected_supplier.email if selected_supplier else None)
        order.contact_name_override = contact_name_override_clean
        order.contact_email_override = contact_email_override_clean
        order.order_kind = normalized_kind
        order.site_id = selected_site_id if normalized_kind == "closed" else None
        order.warehouse_category_id = selected_category_id if normalized_kind == "warehouse" else None
        if normalized_kind == "closed":
            order.delivery_type = DeliveryTypeEnum.SITE.value
            order.delivery_site_id = selected_site_id
            order.delivery_depot_id = None
        else:
            order.delivery_type = DeliveryTypeEnum.PICKUP.value
            order.delivery_site_id = None
            order.delivery_depot_id = None
        db.flush()
        _apply_line_codes_and_catalog(db, order, line_codes, selected_supplier)
        db.commit()
    except IntegrityError:
        db.rollback()
        request_id = _get_request_id(request)
        logger.warning(
            "create order failed (integrity) request_id=%s path=%s user_id=%s",
            request_id,
            request.url.path,
            current_user.id,
        )
        return _render_order_form(
            request,
            db,
            current_user,
            error_message="Dati non validi / vincolo DB.",
            form_data=form_data,
        )
    except Exception:
        db.rollback()
        request_id = _get_request_id(request)
        logger.exception(
            "create order failed",
            extra={
                "request_id": request_id,
                "path": str(request.url.path),
                "user_id": current_user.id,
            },
        )
        return _render_order_form(
            request,
            db,
            current_user,
            error_message="Si è verificato un errore inatteso durante la creazione dell'ordine. Riprova.",
            form_data=form_data,
        )

    return RedirectResponse(
        url=request.url_for("manager_ordini_new"),
        status_code=303,
    )





def _resolve_destination_label(db: Session, destination_type: str, destination_id: str | None) -> str:
    normalized_type = (destination_type or "").strip().lower()
    if normalized_type == "site":
        try:
            site_id = int(destination_id or "")
        except (TypeError, ValueError):
            return "Cantiere non specificato"
        site = db.query(Site).filter(Site.id == site_id).first()
        return f"Cantiere: {site.name}" if site else "Cantiere non specificato"
    if normalized_type == "depot":
        try:
            depot_id = int(destination_id or "")
        except (TypeError, ValueError):
            return "Deposito non specificato"
        depot = db.query(Depot).filter(Depot.id == depot_id).first()
        return f"Deposito: {depot.name}" if depot else "Deposito non specificato"
    return "Ritiro dal fornitore"


@router.get('/api/suppliers/{supplier_id}', name='api_supplier_by_id')
def api_supplier_by_id(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.is_active.is_(True)).first()
    if not supplier:
        raise HTTPException(status_code=404, detail='Fornitore non trovato')
    return {
        'id': supplier.id,
        'name': supplier.name,
        'email': supplier.email,
        'phone': supplier.phone,
        'contact_name': supplier.contact_name,
        'contact_email': supplier.contact_email,
        'contact_phone': supplier.contact_phone,
    }


@router.post('/api/ordini', name='api_ordini_create')
def api_ordini_create(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    supplier_id = payload.get('supplier_id')
    lines = payload.get('lines') or []
    if not supplier_id or not isinstance(lines, list) or not lines:
        raise HTTPException(status_code=400, detail='supplier_id e almeno una riga sono obbligatori')

    supplier = db.query(Supplier).filter(Supplier.id == int(supplier_id)).first()
    if not supplier:
        raise HTTPException(status_code=404, detail='Fornitore non trovato')

    parsed_lines: list[tuple[str, float, int | None]] = []
    for row in lines:
        description = (row.get('description') or '').strip()
        qty = _parse_float(str(row.get('qty_ordered') or ''))
        if not description or qty is None or qty <= 0:
            raise HTTPException(status_code=400, detail='Riga ordine non valida')
        item_id = row.get('magazzino_item_id')
        parsed_lines.append((description, qty, int(item_id) if item_id else None))

    order = _create_order_with_lines(
        db,
        supplier_name=supplier.name,
        supplier_id=supplier.id,
        order_date=_parse_date(payload.get('order_date')),
        requester_user_id=current_user.id,
        lines=parsed_lines,
    )
    order.description = (payload.get('description') or '').strip() or None
    order.order_kind = (payload.get('order_kind') or 'warehouse').strip().lower()
    order.delivery_type = DeliveryTypeEnum.PICKUP.value
    order.delivery_site_id = None
    order.delivery_depot_id = None
    order.supplier_email = None
    order.supplier_phone = None
    order.contact_name = supplier.contact_name
    order.recipient_email = supplier.contact_email or supplier.email
    order.contact_name_override = (payload.get('contact_name_override') or payload.get('contact_name') or '').strip() or None
    order.contact_email_override = (payload.get('contact_email_override') or payload.get('recipient_email') or '').strip() or None
    db.commit()
    return {'ok': True, 'order_id': order.id, 'order_number': order.order_number}



@router.post('/manager/ordini/{order_id}/email/preview', name='manager_ordini_email_preview')
def manager_ordini_email_preview(
    order_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        return JSONResponse({'error': 'order_not_found'}, status_code=404)

    lang = payload.get("lang", "it")
    delivery_type = payload.get("delivery_type")
    delivery_site_id = payload.get("delivery_site_id")
    delivery_depot_id = payload.get("delivery_depot_id")
    to_override = payload.get("to_override")

    recipient = to_override or _order_email_recipient(order)

    if delivery_site_id:
        try:
            order.delivery_site = db.query(Site).filter(Site.id == int(delivery_site_id)).first()
        except (TypeError, ValueError):
            order.delivery_site = None
    if delivery_depot_id:
        try:
            order.delivery_depot = db.query(Depot).filter(Depot.id == int(delivery_depot_id)).first()
        except (TypeError, ValueError):
            order.delivery_depot = None

    subject, body = build_order_email(
        order=order,
        supplier=order.supplier,
        lang=lang,
        delivery_type=delivery_type,
        delivery_site_id=delivery_site_id,
        delivery_depot_id=delivery_depot_id,
    )

    subject_override = payload.get("subject_override")
    body_override = payload.get("body_override")
    if isinstance(subject_override, str) and subject_override.strip():
        subject = subject_override
    if isinstance(body_override, str) and body_override.strip():
        body = body_override

    subject = fix_mojibake(subject)
    body = fix_mojibake(body)

    subject_encoded = quote(subject.encode("cp1252"), safe="")
    body_encoded = quote(body.encode("cp1252"), safe="")

    mailto_url = f"mailto:{recipient}?subject={subject_encoded}&body={body_encoded}"

    logger.info("EMAIL PREVIEW", extra={
        "order_id": order.id,
        "recipient": recipient,
        "subject": subject,
        "body_len": len(body)
    })

    return JSONResponse({
        "to": recipient,
        "subject": subject,
        "body": body,
        "mailto_url": mailto_url,
    })


@router.get(
    '/manager/ordini/' 'email-wizard',
    response_class=HTMLResponse,
    name='manager_ordini_email_wizard',
)
def manager_ordini_email_wizard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order_id = request.query_params.get('order_id')
    if order_id is not None:
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail='Ordine non valido')

        return RedirectResponse(
            url=request.url_for('manager_ordini_email', order_id=order_id),
            status_code=302,
        )

    return render_template(
        templates,
        request,
        'manager/ordini/email_wizard_missing_order.html',
        {},
        db,
        current_user,
        headers={'Content-Type': 'text/html; charset=utf-8'},
    )


@router.get(
    '/manager/ordini/{order_id}/email',
    response_class=HTMLResponse,
    name='manager_ordini_email',
)
def manager_ordini_email(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail='Ordine non trovato')
    recipient = _order_email_recipient(order)
    if not recipient:
        query_string = urlencode({"err": "Email fornitore non disponibile"})
        url = f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
        return RedirectResponse(url=url, status_code=303)

    sites = db.query(Site).filter(Site.is_active.is_(True)).order_by(Site.name.asc()).all()
    depots = db.query(Depot).filter(Depot.is_active.is_(True)).filter(func.lower(func.trim(Depot.name)).notin_(DEFAULT_DEPOT_NAMES)).order_by(Depot.name.asc()).all()
    depots_json = [
        {
            'id': depot.id,
            'name': depot.name,
            'address': _format_depot_full_address(depot),
        }
        for depot in depots
    ]

    default_lang = (request.cookies.get('lang') or 'it').strip().lower()
    if default_lang not in {'it', 'fr'}:
        default_lang = 'it'

    default_delivery_type = (order.delivery_type or DeliveryTypeEnum.PICKUP.value).strip().upper()
    if default_delivery_type not in {DeliveryTypeEnum.SITE.value, DeliveryTypeEnum.DEPOT.value, DeliveryTypeEnum.PICKUP.value}:
        default_delivery_type = DeliveryTypeEnum.PICKUP.value

    return render_template(
        templates,
        request,
        'manager/ordini/email_wizard.html',
        {
            'order': order,
            'supplier': order.supplier,
            'sites': sites,
            'depots': depots,
            'depots_json': depots_json,
            'default_lang': default_lang,
            'default_delivery_type': default_delivery_type,
            'default_delivery_site_id': order.delivery_site_id,
            'default_delivery_depot_id': order.delivery_depot_id,
            'default_to': recipient,
        },
        db,
        current_user,
        headers={'Content-Type': 'text/html; charset=utf-8'},
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
        query = query.outerjoin(Supplier, Supplier.id == PurchaseOrder.supplier_id).filter(
            or_(
                func.lower(PurchaseOrder.supplier_name).contains(supplier_filter.lower()),
                func.lower(Supplier.name).contains(supplier_filter.lower()),
                func.lower(Supplier.email).contains(supplier_filter.lower()),
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
            "supplier_label_map": {order.id: _order_supplier_label(order) for order in orders},
            **_orders_navigation_counts(db),
        },
        db,
        current_user,
    )


@router.get(
    "/manager/ordini/chiusi",
    response_class=HTMLResponse,

    name="manager_ordini_closed",
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
            "magazzino_item": line.magazzino_item,
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
    pending_discharge_requirements, pending_discharge_deliveries = (
        _collect_pending_discharge_requirements(db, order)
    )
    error_message = request.query_params.get("err")
    email_recipient = _order_email_recipient(order)
    can_send_email = bool(email_recipient)

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
            "supplier_label": _order_supplier_label(order),
            "can_send_email": can_send_email,
            "email_disabled_message": (
                "Email fornitore non disponibile"
                if not can_send_email
                else ""
            ),
            "can_discharge": order.order_kind == "closed" and order.site_id is not None,
            "has_pending_discharge": bool(pending_discharge_deliveries),
            "pending_discharge_qty": round(
                sum(pending_discharge_requirements.values()), 2
            ),
        },
        db,
        current_user,
    )


@router.get(
    "/manager/ordini/{order_id}/fattura",
    response_class=HTMLResponse,
    name="manager_ordini_fattura_form",
)
def manager_ordini_fattura_form(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    return render_template(
        templates,
        request,
        "manager/ordini/fattura_form.html",
        {
            "order": order,
            "error_message": None,
            "form_data": {
                "invoice_number": order.invoice_number or "",
                "invoice_date": order.invoice_date.strftime("%Y-%m-%d") if order.invoice_date else "",
            },
        },
        db,
        current_user,
    )


@router.post(
    "/manager/ordini/{order_id}/fattura",
    response_class=HTMLResponse,
    name="manager_ordini_fattura_save",
)
def manager_ordini_fattura_save(
    request: Request,
    order_id: int,
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    invoice_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    parsed_invoice_date = _parse_date(invoice_date)
    if invoice_date and not parsed_invoice_date:
        return render_template(
            templates,
            request,
            "manager/ordini/fattura_form.html",
            {
                "order": order,
                "error_message": "Data fattura non valida.",
                "form_data": {
                    "invoice_number": invoice_number or "",
                    "invoice_date": invoice_date or "",
                },
            },
            db,
            current_user,
        )

    if invoice_file and invoice_file.filename:
        INVOICE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        extension = Path(invoice_file.filename).suffix
        file_name = f"ordine-{order.id}-{uuid4().hex}{extension}"
        destination = INVOICE_UPLOAD_DIR / file_name
        with destination.open("wb") as output:
            shutil.copyfileobj(invoice_file.file, output)
        order.file_invoice = f"uploads/invoices/{file_name}"

    order.invoice_number = invoice_number.strip() or None
    order.invoice_date = parsed_invoice_date
    db.add(order)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_ordini_detail", order_id=order.id),
        status_code=303,
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

    return _render_bolla_form(request, db, current_user, order=order)


@router.post(
    "/manager/ordini/{order_id}/bolle/nuova",
    response_class=HTMLResponse,
    name="manager_ordini_bolle_create",
)
def manager_ordini_bolle_create(
    request: Request,
    order_id: int,
    delivery_number: str = Form(""),
    order_line_id: list[int] = Form(...),
    qty_delivered: list[str] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    clean_delivery_number = delivery_number.strip()
    if not clean_delivery_number:
        return _render_bolla_form(
            request,
            db,
            current_user,
            order=order,
            error_message="Inserisci il numero bolla.",
            form_data={"delivery_number": ""},
        )

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

    delivery = PurchaseDelivery(
        order_id=order.id,
        delivery_number=clean_delivery_number,
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


@router.post(
    "/manager/ordini/{order_id}/scarico",
    name="manager_ordini_scarico",
)
def manager_ordini_scarico(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    if order.order_kind != "closed" or order.site_id is None:
        query_string = urlencode(
            {"err": "Scarico disponibile solo per ordini chiusi associati a un cantiere."}
        )
        url = f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
        return RedirectResponse(url=url, status_code=303)

    required_by_item, pending_deliveries = _collect_pending_discharge_requirements(db, order)
    if not pending_deliveries:
        query_string = urlencode({"err": "Nessuna bolla confermata da scaricare."})
        url = f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
        return RedirectResponse(url=url, status_code=303)

    if not required_by_item:
        query_string = urlencode(
            {"err": "Nessuna quantità valida da scaricare per le bolle confermate."}
        )
        url = f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
        return RedirectResponse(url=url, status_code=303)

    items = {
        item.id: item
        for item in db.query(MagazzinoItem)
        .filter(MagazzinoItem.id.in_(list(required_by_item.keys())))
        .all()
    }
    for item_id, required_qty in required_by_item.items():
        item = items.get(item_id)
        if not item:
            query_string = urlencode({"err": "Articolo magazzino non valido per lo scarico."})
            url = (
                f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
            )
            return RedirectResponse(url=url, status_code=303)
        available_qty = item.quantita_disponibile or 0.0
        if available_qty < required_qty:
            query_string = urlencode(
                {
                    "err": (
                        f"Stock insufficiente per {item.codice or item.nome or f'ID {item.id}'}: "
                        f"disponibile {available_qty}, richiesto {required_qty}."
                    )
                }
            )
            url = (
                f"{request.url_for('manager_ordini_detail', order_id=order.id)}?{query_string}"
            )
            return RedirectResponse(url=url, status_code=303)

    for delivery in pending_deliveries:
        for line in delivery.lines:
            if not line.order_line:
                continue
            item_id = line.order_line.magazzino_item_id
            qty = line.qty_delivered or 0.0
            if item_id is None or qty <= 0:
                continue
            item = items.get(item_id)
            if not item:
                continue
            item.quantita_disponibile = (item.quantita_disponibile or 0.0) - qty
            db.add(item)
            db.add(
                MagazzinoMovimento(
                    item_id=item.id,
                    tipo=MagazzinoMovimentoTipoEnum.scarico,
                    quantita=qty,
                    cantiere_id=order.site_id,
                    creato_da_user_id=current_user.id,
                    purchase_order_id=order.id,
                    purchase_delivery_id=delivery.id,
                    note=f"Scarico ordine {order.order_number} · bolla {delivery.delivery_number}",
                )
            )

    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_ordini_detail", order_id=order.id),
        status_code=303,
    )
