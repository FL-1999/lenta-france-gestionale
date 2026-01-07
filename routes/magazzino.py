from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from math import ceil
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from auth import get_current_active_user_html
from database import get_db
from models import (
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    MagazzinoRichiesta,
    MagazzinoRichiestaRiga,
    MagazzinoRichiestaPrioritaEnum,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    Site,
    User,
)
from audit_utils import log_audit_event
from template_context import (
    invalidate_manager_badges_cache,
    register_manager_badges,
    render_template,
)
from permissions import has_perm
from notifications import notify_magazzino_richiesta


templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["magazzino"])

DEFAULT_CATEGORIA_ICON = "📦"
DEFAULT_CATEGORIA_COLOR = "indigo"
CATEGORIA_COLOR_MAP = {
    "indigo": "#4f46e5",
    "emerald": "#10b981",
    "amber": "#f59e0b",
    "rose": "#f43f5e",
    "slate": "#64748b",
}
CATEGORIA_COLOR_OPTIONS = list(CATEGORIA_COLOR_MAP.keys())
MAX_CATEGORIA_ICON_LENGTH = 32
MAX_CATEGORIA_COLOR_LENGTH = 20
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100


def ensure_caposquadra_or_manager(user: User) -> None:
    if user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def ensure_magazzino_manager(user: User) -> None:
    if has_perm(user, "manager.access") or has_perm(user, "inventory.manage"):
        return
    raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _invalidate_magazzino_cache() -> None:
    invalidate_manager_badges_cache()


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_status(value: str | None) -> MagazzinoRichiestaStatusEnum | None:
    if not value:
        return None
    for status in MagazzinoRichiestaStatusEnum:
        if value.lower() in (status.value.lower(), status.name.lower()):
            return status
    return None


def _parse_categoria_id(value: str | None) -> int | None:
    if value in (None, "", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _log_audit(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: int | None,
    details: dict | None = None,
) -> None:
    log_audit_event(
        db,
        user,
        action,
        entity,
        entity_id,
        details,
    )


def _clean_short_text(value: str | None, max_length: int) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"Il valore deve avere massimo {max_length} caratteri.")
    return cleaned


def _normalize_categoria_fields(icon: str | None, color: str | None) -> tuple[str | None, str | None]:
    icon_value = _clean_short_text(icon, MAX_CATEGORIA_ICON_LENGTH)
    color_value = _clean_short_text(color, MAX_CATEGORIA_COLOR_LENGTH)
    if color_value:
        color_value = color_value.lower()
        if color_value not in CATEGORIA_COLOR_OPTIONS:
            raise ValueError("Seleziona un colore valido.")
    return icon_value, color_value


def _categoria_color_style(color: str | None) -> str:
    resolved_color = (color or DEFAULT_CATEGORIA_COLOR).lower()
    hex_color = CATEGORIA_COLOR_MAP.get(resolved_color, CATEGORIA_COLOR_MAP[DEFAULT_CATEGORIA_COLOR])
    return f"background-color: {hex_color}; color: #ffffff;"


def _slugify(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return "categoria"
    slug_chars: list[str] = []
    last_dash = False
    for char in cleaned:
        if char.isalnum():
            slug_chars.append(char)
            last_dash = False
        else:
            if not last_dash:
                slug_chars.append("-")
                last_dash = True
    slug = "".join(slug_chars).strip("-")
    return slug or "categoria"


def _ensure_unique_slug(
    db: Session,
    base_slug: str,
    exclude_id: int | None = None,
) -> str:
    slug = base_slug
    counter = 2
    while True:
        query = db.query(MagazzinoCategoria).filter(MagazzinoCategoria.slug == slug)
        if exclude_id is not None:
            query = query.filter(MagazzinoCategoria.id != exclude_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_priorita(value: str | None) -> MagazzinoRichiestaPrioritaEnum | None:
    if not value:
        return None
    normalized = value.strip().upper()
    for priorita in MagazzinoRichiestaPrioritaEnum:
        if priorita.value == normalized:
            return priorita
    return None


def _group_items_by_categoria(
    items: list[MagazzinoItem],
    categorie: list[MagazzinoCategoria],
    fallback_categoria_id: int | None,
) -> dict[int | None, list[MagazzinoItem]]:
    valid_ids = {categoria.id for categoria in categorie if categoria.id is not None}
    grouped: dict[int | None, list[MagazzinoItem]] = {
        categoria.id: [] for categoria in categorie
    }
    if fallback_categoria_id not in grouped:
        grouped[fallback_categoria_id] = []
    for item in items:
        if item.categoria_id in valid_ids:
            categoria_id = item.categoria_id
        else:
            categoria_id = fallback_categoria_id
        if categoria_id not in grouped:
            grouped[categoria_id] = []
        grouped[categoria_id].append(item)
    return grouped


def _load_categorie(
    db: Session,
    include_inactive: bool = False,
    include_fallback: bool = True,
) -> tuple[list[MagazzinoCategoria | SimpleNamespace], SimpleNamespace, int | None]:
    query = db.query(MagazzinoCategoria)
    if not include_inactive:
        query = query.filter(MagazzinoCategoria.attiva.is_(True))
    categorie = query.order_by(
        MagazzinoCategoria.ordine.asc(),
        MagazzinoCategoria.nome.asc(),
    ).all()
    fallback = SimpleNamespace(
        id=None,
        nome="Senza categoria",
        slug="senza-categoria",
        attiva=True,
        icon=DEFAULT_CATEGORIA_ICON,
        color=DEFAULT_CATEGORIA_COLOR,
    )
    if include_fallback:
        return [*categorie, fallback], fallback, None
    return categorie, fallback, None


def _load_active_categorie(db: Session) -> list[MagazzinoCategoria]:
    return (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.attiva.is_(True))
        .order_by(MagazzinoCategoria.ordine.asc(), MagazzinoCategoria.nome.asc())
        .all()
    )


def _swap_categoria_order(
    db: Session,
    categoria: MagazzinoCategoria,
    direction: str,
) -> None:
    categorie = _load_active_categorie(db)
    categoria_index = next(
        (index for index, item in enumerate(categorie) if item.id == categoria.id),
        None,
    )
    if categoria_index is None:
        return
    if direction == "su":
        if categoria_index == 0:
            return
        other = categorie[categoria_index - 1]
    elif direction == "giu":
        if categoria_index >= len(categorie) - 1:
            return
        other = categorie[categoria_index + 1]
    else:
        return
    categoria.ordine, other.ordine = other.ordine, categoria.ordine
    db.add(categoria)
    db.add(other)
    db.commit()
    _invalidate_magazzino_cache()


def _order_categorie_for_display(
    categorie: list[MagazzinoCategoria | SimpleNamespace],
) -> list[MagazzinoCategoria | SimpleNamespace]:
    fallback = [categoria for categoria in categorie if categoria.id is None]
    others = [categoria for categoria in categorie if categoria.id is not None]
    return [*others, *fallback]


def _build_categoria_sections(
    categorie: list[MagazzinoCategoria | SimpleNamespace],
    items_by_categoria: dict[int | None, list[MagazzinoItem]],
) -> list[dict[str, object]]:
    sections = []
    for categoria in categorie:
        items = items_by_categoria.get(categoria.id, [])
        sotto_soglia_count = sum(
            1
            for item in items
            if item.soglia_minima is not None
            and item.quantita_disponibile is not None
            and item.quantita_disponibile <= item.soglia_minima
        )
        esauriti_count = sum(
            1
            for item in items
            if item.quantita_disponibile is not None
            and item.quantita_disponibile <= 0
        )
        icon_value = getattr(categoria, "icon", None) or DEFAULT_CATEGORIA_ICON
        color_value = getattr(categoria, "color", None) or DEFAULT_CATEGORIA_COLOR
        sections.append(
            {
                "cat": categoria,
                "items": items,
                "stats": {
                    "total_items": len(items),
                    "sotto_soglia_count": sotto_soglia_count,
                    "esauriti_count": esauriti_count,
                },
                "icon": icon_value,
                "color": color_value,
                "color_style": _categoria_color_style(color_value),
            }
        )
    return sections


@router.get(
    "/capo/magazzino",
    response_class=HTMLResponse,
    name="capo_magazzino_list",
)
def capo_magazzino_list(
    request: Request,
    q: str | None = None,
    categoria: str | None = None,
    sotto_soglia: int | None = None,
    esauriti: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)
    categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
        db,
        include_inactive=False,
        include_fallback=True,
    )
    query = (
        db.query(MagazzinoItem)
        .options(selectinload(MagazzinoItem.categoria))
        .filter(MagazzinoItem.attivo.is_(True))
    )
    q_value = (q or "").strip()
    if q_value:
        like_pattern = f"%{q_value}%"
        query = query.filter(
            or_(
                MagazzinoItem.codice.ilike(like_pattern),
                MagazzinoItem.nome.ilike(like_pattern),
            )
        )
    categoria_id = _parse_categoria_id(categoria)
    if categoria == "none":
        query = query.filter(MagazzinoItem.categoria_id.is_(None))
    elif categoria_id is not None:
        if fallback_categoria_id and categoria_id == fallback_categoria_id:
            query = query.filter(
                or_(
                    MagazzinoItem.categoria_id == categoria_id,
                    MagazzinoItem.categoria_id.is_(None),
                )
            )
        else:
            query = query.filter(MagazzinoItem.categoria_id == categoria_id)
    if sotto_soglia == 1:
        query = query.filter(
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
    if esauriti == 1:
        query = query.filter(MagazzinoItem.quantita_disponibile <= 0)
    items = (
        query.outerjoin(MagazzinoCategoria)
        .order_by(
            MagazzinoCategoria.ordine.asc(),
            MagazzinoCategoria.nome.asc(),
            MagazzinoItem.preferito.desc(),
            MagazzinoItem.nome.asc(),
            MagazzinoItem.codice.asc(),
        )
        .all()
    )
    items_by_categoria = _group_items_by_categoria(
        items,
        [categoria for categoria in categorie if isinstance(categoria, MagazzinoCategoria)],
        fallback_categoria_id,
    )
    categorie_display = _order_categorie_for_display(categorie)
    categorie_sections = _build_categoria_sections(categorie_display, items_by_categoria)
    filters = {
        "q": q_value,
        "categoria": categoria or "",
        "sotto_soglia": sotto_soglia == 1,
        "esauriti": esauriti == 1,
    }
    return render_template(
        templates,
        request,
        "capo/magazzino/items_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie_display,
            "categorie_sections": categorie_sections,
            "fallback_categoria": fallback_categoria,
            "items_by_categoria": items_by_categoria,
            "items_count": len(items),
            "filters": filters,
        },
        db,
        current_user,
    )


@router.get(
    "/capo/magazzino/richieste",
    response_class=HTMLResponse,
    name="capo_magazzino_richieste",
)
def capo_magazzino_richieste(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)
    page, per_page = _normalize_pagination(page, per_page)
    query = (
        db.query(MagazzinoRichiesta)
        .options(
            selectinload(MagazzinoRichiesta.righe).selectinload(
                MagazzinoRichiestaRiga.item
            ),
            joinedload(MagazzinoRichiesta.cantiere),
            joinedload(MagazzinoRichiesta.gestito_da),
        )
        .filter(MagazzinoRichiesta.richiesto_da_user_id == current_user.id)
        .order_by(MagazzinoRichiesta.created_at.desc())
    )
    total_count = query.count()
    total_pages = max(1, ceil(total_count / per_page))
    richieste = query.offset((page - 1) * per_page).limit(per_page).all()
    unread_ids = [
        richiesta.id
        for richiesta in richieste
        if richiesta.gestito_at and not richiesta.letto_da_richiedente
    ]
    if unread_ids:
        db.query(MagazzinoRichiesta).filter(
            MagazzinoRichiesta.id.in_(unread_ids)
        ).update(
            {MagazzinoRichiesta.letto_da_richiedente: True},
            synchronize_session=False,
        )
        db.commit()
        _invalidate_magazzino_cache()
    return render_template(
        templates,
        request,
        "capo/magazzino/richieste_list.html",
        {
            "request": request,
            "user": current_user,
            "richieste": richieste,
            "unread_ids": set(unread_ids),
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
        db,
        current_user,
    )


@router.post(
    "/capo/magazzino/richieste/{richiesta_id}/letto",
    response_class=HTMLResponse,
    name="capo_magazzino_richiesta_letto",
)
def capo_magazzino_richiesta_letto(
    richiesta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)
    richiesta = (
        db.query(MagazzinoRichiesta)
        .filter(
            MagazzinoRichiesta.id == richiesta_id,
            MagazzinoRichiesta.richiesto_da_user_id == current_user.id,
        )
        .first()
    )
    if richiesta and richiesta.gestito_at:
        richiesta.letto_da_richiedente = True
        db.add(richiesta)
        _log_audit(
            db,
            current_user,
            "RICHIESTA_CONSEGNATA",
            "MagazzinoRichiesta",
            richiesta.id,
            {"stato": richiesta.stato.value if richiesta.stato else None},
        )
        db.commit()
        _invalidate_magazzino_cache()

    return RedirectResponse(
        url=request.url_for("capo_magazzino_richieste"),
        status_code=303,
    )


@router.get(
    "/capo/magazzino/richieste/nuova",
    response_class=HTMLResponse,
    name="capo_magazzino_richiesta_new",
)
def capo_magazzino_richiesta_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)
    items = (
        db.query(MagazzinoItem)
        .filter(MagazzinoItem.attivo.is_(True))
        .order_by(MagazzinoItem.nome.asc())
        .all()
    )
    return render_template(
        templates,
        request,
        "capo/magazzino/richieste_new.html",
        {
            "request": request,
            "user": current_user,
            "items": items,
            "priorita_options": list(MagazzinoRichiestaPrioritaEnum),
        },
        db,
        current_user,
    )


@router.post(
    "/capo/magazzino/richieste/nuova",
    response_class=HTMLResponse,
    name="capo_magazzino_richiesta_create",
)
def capo_magazzino_richiesta_create(
    request: Request,
    item_id: list[str] = Form(...),
    quantita: list[str] = Form(...),
    note: str = Form(""),
    priorita: str = Form("MED"),
    data_necessaria: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)

    righe_map: dict[int, float] = {}
    for raw_item_id, raw_quantita in zip(item_id, quantita):
        if not raw_item_id and not raw_quantita:
            continue
        try:
            parsed_item_id = int(raw_item_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Item non valido")
        parsed_quantita = _parse_float(raw_quantita)
        if parsed_quantita is None or parsed_quantita <= 0:
            raise HTTPException(status_code=400, detail="Quantità non valida")

        righe_map[parsed_item_id] = righe_map.get(parsed_item_id, 0.0) + parsed_quantita

    if not righe_map:
        raise HTTPException(status_code=400, detail="Nessuna riga valida")

    items = (
        db.query(MagazzinoItem)
        .filter(MagazzinoItem.id.in_(righe_map.keys()))
        .all()
    )
    items_by_id = {item.id: item for item in items}
    for item_id_value in righe_map:
        item = items_by_id.get(item_id_value)
        if not item or not item.attivo:
            raise HTTPException(status_code=400, detail="Item non disponibile")

    parsed_priorita = _parse_priorita(priorita) or MagazzinoRichiestaPrioritaEnum.med
    parsed_data_necessaria = _parse_date(data_necessaria)
    richiesta = MagazzinoRichiesta(
        richiesto_da_user_id=current_user.id,
        note=note.strip() or None,
        priorita=parsed_priorita,
        data_necessaria=parsed_data_necessaria,
    )
    db.add(richiesta)
    db.flush()

    for item_id_value, quantita_value in righe_map.items():
        db.add(
            MagazzinoRichiestaRiga(
                richiesta_id=richiesta.id,
                item_id=item_id_value,
                quantita_richiesta=quantita_value,
            )
        )

    notify_magazzino_richiesta(db, richiesta, current_user)
    db.commit()
    _invalidate_magazzino_cache()

    return RedirectResponse(
        url=request.url_for("capo_magazzino_richieste"),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/dashboard",
    response_class=HTMLResponse,
    name="manager_magazzino_dashboard",
)
def manager_magazzino_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    sotto_soglia_count = (
        db.query(func.count(MagazzinoItem.id))
        .filter(
            MagazzinoItem.attivo.is_(True),
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
        .scalar()
        or 0
    )
    esauriti_count = (
        db.query(func.count(MagazzinoItem.id))
        .filter(
            MagazzinoItem.attivo.is_(True),
            MagazzinoItem.quantita_disponibile <= 0,
        )
        .scalar()
        or 0
    )
    richieste_nuove_count = (
        db.query(func.count(MagazzinoRichiesta.id))
        .filter(MagazzinoRichiesta.stato == MagazzinoRichiestaStatusEnum.in_attesa)
        .scalar()
        or 0
    )
    since_date = datetime.now() - timedelta(days=30)
    top_consumi_rows = (
        db.query(
            MagazzinoItem.codice,
            MagazzinoItem.nome,
            func.coalesce(func.sum(MagazzinoMovimento.quantita), 0.0).label("totale"),
        )
        .join(MagazzinoMovimento, MagazzinoMovimento.item_id == MagazzinoItem.id)
        .filter(
            MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
            MagazzinoMovimento.created_at >= since_date,
        )
        .group_by(MagazzinoItem.id)
        .order_by(func.sum(MagazzinoMovimento.quantita).desc(), MagazzinoItem.nome.asc())
        .limit(10)
        .all()
    )
    top_consumi = [
        SimpleNamespace(codice=codice, nome=nome, totale=totale)
        for codice, nome, totale in top_consumi_rows
    ]
    return render_template(
        templates,
        request,
        "manager/magazzino/dashboard.html",
        {
            "request": request,
            "user": current_user,
            "sotto_soglia_count": sotto_soglia_count,
            "esauriti_count": esauriti_count,
            "richieste_nuove_count": richieste_nuove_count,
            "top_consumi": top_consumi,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino",
    response_class=HTMLResponse,
    name="manager_magazzino_list",
)
def manager_magazzino_list(
    request: Request,
    q: str | None = None,
    categoria: str | None = None,
    attivi: int | None = None,
    sotto_soglia: int | None = None,
    esauriti: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    ok = request.query_params.get("ok")
    err = request.query_params.get("err")
    success_message = None
    if ok == "carico":
        success_message = (
            "Chargement enregistré avec succès."
            if lang == "fr"
            else "Carico registrato con successo."
        )
    elif ok == "scarico":
        success_message = (
            "Déchargement enregistré avec succès."
            if lang == "fr"
            else "Scarico registrato con successo."
        )
    elif ok:
        success_message = (
            "Opération terminée avec succès."
            if lang == "fr"
            else "Operazione completata con successo."
        )
    error_message = _magazzino_error_message(lang, err) if err else None
    return _render_magazzino_items_list(
        request,
        db,
        current_user,
        q=q,
        categoria=categoria,
        attivi=attivi,
        sotto_soglia=sotto_soglia,
        esauriti=esauriti,
        success_message=success_message,
        error_message=error_message,
    )


def _magazzino_error_message(lang: str, err_code: str | None) -> str | None:
    if err_code == "item_non_trovato":
        return "Article introuvable." if lang == "fr" else "Articolo non trovato."
    if err_code == "quantita_non_valida":
        return "Quantité non valide." if lang == "fr" else "Quantità non valida."
    if err_code == "quantita_insufficiente":
        return (
            "Quantité insuffisante en stock."
            if lang == "fr"
            else "Quantità insufficiente in magazzino."
        )
    if err_code:
        return (
            "Erreur lors de l'opération."
            if lang == "fr"
            else "Errore durante l'operazione."
        )
    return None


def _render_magazzino_items_list(
    request: Request,
    db: Session,
    current_user: User,
    *,
    q: str | None = None,
    categoria: str | None = None,
    attivi: int | None = None,
    sotto_soglia: int | None = None,
    esauriti: int | None = None,
    success_message: str | None = None,
    error_message: str | None = None,
):
    categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
        db,
        include_inactive=False,
        include_fallback=True,
    )
    query = db.query(MagazzinoItem).options(selectinload(MagazzinoItem.categoria))
    q_value = (q or "").strip()
    if q_value:
        like_pattern = f"%{q_value}%"
        query = query.filter(
            or_(
                MagazzinoItem.codice.ilike(like_pattern),
                MagazzinoItem.nome.ilike(like_pattern),
            )
        )
    categoria_id = _parse_categoria_id(categoria)
    if categoria == "none":
        query = query.filter(MagazzinoItem.categoria_id.is_(None))
    elif categoria_id is not None:
        if fallback_categoria_id and categoria_id == fallback_categoria_id:
            query = query.filter(
                or_(
                    MagazzinoItem.categoria_id == categoria_id,
                    MagazzinoItem.categoria_id.is_(None),
                )
            )
        else:
            query = query.filter(MagazzinoItem.categoria_id == categoria_id)
    if attivi == 1:
        query = query.filter(MagazzinoItem.attivo.is_(True))
    if sotto_soglia == 1:
        query = query.filter(
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
    if esauriti == 1:
        query = query.filter(MagazzinoItem.quantita_disponibile <= 0)
    items = (
        query.outerjoin(MagazzinoCategoria)
        .order_by(
            MagazzinoCategoria.ordine.asc(),
            MagazzinoCategoria.nome.asc(),
            MagazzinoItem.preferito.desc(),
            MagazzinoItem.nome.asc(),
            MagazzinoItem.codice.asc(),
        )
        .all()
    )
    cantieri = (
        db.query(Site)
        .filter(Site.is_active.is_(True))
        .order_by(Site.name.asc())
        .all()
    )
    items_by_categoria = _group_items_by_categoria(
        items,
        [categoria for categoria in categorie if isinstance(categoria, MagazzinoCategoria)],
        fallback_categoria_id,
    )
    categorie_display = _order_categorie_for_display(categorie)
    categorie_sections = _build_categoria_sections(categorie_display, items_by_categoria)
    filters = {
        "q": q_value,
        "categoria": categoria or "",
        "attivi": attivi == 1,
        "sotto_soglia": sotto_soglia == 1,
        "esauriti": esauriti == 1,
    }
    return render_template(
        templates,
        request,
        "manager/magazzino/items_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie_display,
            "categorie_sections": categorie_sections,
            "fallback_categoria": fallback_categoria,
            "default_categoria_id": fallback_categoria_id,
            "items_by_categoria": items_by_categoria,
            "items_count": len(items),
            "filters": filters,
            "cantieri": cantieri,
            "color_options": CATEGORIA_COLOR_OPTIONS,
            "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
            "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            "success_message": success_message,
            "error_message": error_message,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino/sotto-soglia",
    response_class=HTMLResponse,
    name="manager_magazzino_sotto_soglia",
)
def manager_magazzino_sotto_soglia(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    items = (
        db.query(MagazzinoItem)
        .filter(
            MagazzinoItem.attivo.is_(True),
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
        .order_by(MagazzinoItem.nome.asc())
        .all()
    )
    items_with_order = []
    for item in items:
        if item.soglia_minima is None or item.quantita_disponibile is None:
            da_ordinare = None
        else:
            da_ordinare = max(item.soglia_minima - item.quantita_disponibile, 1)
        items_with_order.append(
            SimpleNamespace(
                item=item,
                da_ordinare=da_ordinare,
            )
        )
    suggested_entries = [
        entry
        for entry in items_with_order
        if entry.da_ordinare is not None and entry.da_ordinare > 0
    ]

    return render_template(
        templates,
        request,
        "manager/magazzino/sotto_soglia.html",
        {
            "request": request,
            "user": current_user,
            "items": items_with_order,
            "items_count": len(items_with_order),
            "suggested_entries": suggested_entries,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/sotto-soglia/crea-richiesta",
    response_class=HTMLResponse,
    name="manager_magazzino_sotto_soglia_crea_richiesta",
)
def manager_magazzino_sotto_soglia_crea_richiesta(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    items = (
        db.query(MagazzinoItem)
        .filter(
            MagazzinoItem.attivo.is_(True),
            MagazzinoItem.soglia_minima.isnot(None),
            MagazzinoItem.quantita_disponibile <= MagazzinoItem.soglia_minima,
        )
        .order_by(MagazzinoItem.nome.asc())
        .all()
    )
    if not items:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_sotto_soglia"),
            status_code=303,
        )

    richiesta = MagazzinoRichiesta(
        richiesto_da_user_id=current_user.id,
        stato=MagazzinoRichiestaStatusEnum.in_attesa,
        note="Auto-generata da sotto soglia",
    )
    db.add(richiesta)
    db.flush()

    for item in items:
        if item.soglia_minima is None or item.quantita_disponibile is None:
            continue
        quantita_richiesta = max(item.soglia_minima - item.quantita_disponibile, 1)
        db.add(
            MagazzinoRichiestaRiga(
                richiesta_id=richiesta.id,
                item_id=item.id,
                quantita_richiesta=quantita_richiesta,
            )
        )

    db.commit()
    _invalidate_magazzino_cache()

    return RedirectResponse(
        url=(
            f"{request.url_for('manager_magazzino_richiesta_detail', richiesta_id=richiesta.id)}"
            "?ok=creata"
        ),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/richieste/bozza-sotto-soglia",
    response_class=HTMLResponse,
    name="manager_magazzino_richiesta_draft_sotto_soglia",
)
def manager_magazzino_richiesta_draft_sotto_soglia(
    request: Request,
    item_id: list[str] = Form([]),
    quantita: list[str] = Form([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    righe_map: dict[int, float] = {}
    for raw_item_id, raw_quantita in zip(item_id, quantita):
        if not raw_item_id and not raw_quantita:
            continue
        try:
            parsed_item_id = int(raw_item_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Item non valido")
        parsed_quantita = _parse_float(raw_quantita)
        if parsed_quantita is None or parsed_quantita <= 0:
            raise HTTPException(status_code=400, detail="Quantità non valida")

        righe_map[parsed_item_id] = righe_map.get(parsed_item_id, 0.0) + parsed_quantita

    if not righe_map:
        raise HTTPException(status_code=400, detail="Nessuna riga valida")

    items = (
        db.query(MagazzinoItem)
        .filter(MagazzinoItem.id.in_(righe_map.keys()))
        .all()
    )
    items_by_id = {item.id: item for item in items}
    for item_id_value in righe_map:
        item = items_by_id.get(item_id_value)
        if not item or not item.attivo:
            raise HTTPException(status_code=400, detail="Item non disponibile")

    richiesta = MagazzinoRichiesta(
        richiesto_da_user_id=current_user.id,
    )
    db.add(richiesta)
    db.flush()

    for item_id_value, quantita_value in righe_map.items():
        db.add(
            MagazzinoRichiestaRiga(
                richiesta_id=richiesta.id,
                item_id=item_id_value,
                quantita_richiesta=quantita_value,
            )
        )

    db.commit()
    _invalidate_magazzino_cache()

    return RedirectResponse(
        url=request.url_for("manager_magazzino_richiesta_detail", richiesta_id=richiesta.id),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/movimenti",
    response_class=HTMLResponse,
    name="manager_magazzino_movimenti",
)
def manager_magazzino_movimenti(
    request: Request,
    q: str | None = None,
    cantiere_id: int | None = None,
    item_id: int | None = None,
    tipo: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    export: str | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    page, per_page = _normalize_pagination(page, per_page)
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    query = db.query(MagazzinoMovimento).options(
        joinedload(MagazzinoMovimento.item),
        joinedload(MagazzinoMovimento.cantiere),
        joinedload(MagazzinoMovimento.creato_da_user),
    )
    if q:
        search = f"%{q.strip()}%"
        query = query.join(MagazzinoItem).filter(
            or_(
                MagazzinoItem.codice.ilike(search),
                MagazzinoItem.nome.ilike(search),
            )
        )
    if cantiere_id:
        query = query.filter(MagazzinoMovimento.cantiere_id == cantiere_id)
    if item_id:
        query = query.filter(MagazzinoMovimento.item_id == item_id)
    if tipo in (
        MagazzinoMovimentoTipoEnum.scarico.value,
        MagazzinoMovimentoTipoEnum.carico.value,
        MagazzinoMovimentoTipoEnum.rettifica.value,
    ):
        query = query.filter(MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum(tipo))
    if parsed_from:
        query = query.filter(
            MagazzinoMovimento.created_at >= datetime.combine(parsed_from, time.min)
        )
    if parsed_to:
        query = query.filter(
            MagazzinoMovimento.created_at <= datetime.combine(parsed_to, time.max)
        )

    total_count = query.count()
    total_pages = max(1, ceil(total_count / per_page))
    movimenti_query = query.order_by(MagazzinoMovimento.created_at.desc())
    if export != "csv":
        movimenti_query = movimenti_query.offset((page - 1) * per_page).limit(per_page)
    movimenti = movimenti_query.all()
    if export == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "Data",
                "Codice articolo",
                "Nome articolo",
                "Tipo",
                "Quantità",
                "Cantiere",
                "Utente",
                "Note",
                "Richiesta",
            ]
        )
        for movimento in movimenti:
            created_at = (
                movimento.created_at.strftime("%Y-%m-%d %H:%M")
                if movimento.created_at
                else ""
            )
            item_code = movimento.item.codice if movimento.item else ""
            item_name = movimento.item.nome if movimento.item else ""
            user_label = ""
            if movimento.creato_da_user:
                user_label = movimento.creato_da_user.full_name or movimento.creato_da_user.email
            writer.writerow(
                [
                    created_at,
                    item_code or "",
                    item_name or "",
                    movimento.tipo.value if movimento.tipo else "",
                    movimento.quantita,
                    movimento.cantiere.name if movimento.cantiere else "",
                    user_label or "",
                    movimento.note or "",
                    movimento.riferimento_richiesta_id or "",
                ]
            )
        filename = f"movimenti_magazzino_{datetime.now().strftime('%Y%m%d')}.csv"
        response = Response(output.getvalue(), media_type="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    summary_query = db.query(
        Site,
        func.coalesce(func.sum(MagazzinoMovimento.quantita), 0.0),
    ).join(
        MagazzinoMovimento,
        MagazzinoMovimento.cantiere_id == Site.id,
    ).filter(
        MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
    )
    if q:
        search = f"%{q.strip()}%"
        summary_query = summary_query.join(
            MagazzinoItem,
            MagazzinoMovimento.item_id == MagazzinoItem.id,
        ).filter(
            or_(
                MagazzinoItem.codice.ilike(search),
                MagazzinoItem.nome.ilike(search),
            )
        )
    if cantiere_id:
        summary_query = summary_query.filter(MagazzinoMovimento.cantiere_id == cantiere_id)
    if item_id:
        summary_query = summary_query.filter(MagazzinoMovimento.item_id == item_id)
    if parsed_from:
        summary_query = summary_query.filter(
            MagazzinoMovimento.created_at >= datetime.combine(parsed_from, time.min)
        )
    if parsed_to:
        summary_query = summary_query.filter(
            MagazzinoMovimento.created_at <= datetime.combine(parsed_to, time.max)
        )
    totals = (
        summary_query.group_by(Site.id)
        .order_by(Site.name.asc())
        .all()
    )

    cantieri = db.query(Site).order_by(Site.name.asc()).all()
    items = db.query(MagazzinoItem).order_by(MagazzinoItem.nome.asc()).all()

    return render_template(
        templates,
        request,
        "manager/magazzino/movimenti_list.html",
        {
            "request": request,
            "user": current_user,
            "movimenti": movimenti,
            "cantieri": cantieri,
            "items": items,
            "tipo_options": [tipo.value for tipo in MagazzinoMovimentoTipoEnum],
            "selected": {
                "q": q or "",
                "cantiere_id": cantiere_id,
                "item_id": item_id,
                "tipo": tipo,
                "date_from": parsed_from.isoformat() if parsed_from else "",
                "date_to": parsed_to.isoformat() if parsed_to else "",
            },
            "totals": totals,
            "has_period_filter": bool(parsed_from or parsed_to),
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino/report-consumi",
    response_class=HTMLResponse,
    name="manager_magazzino_report_consumi",
)
def manager_magazzino_report_consumi(
    request: Request,
    cantiere_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    export: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    if not cantiere_id:
        raise HTTPException(status_code=400, detail="Cantiere obbligatorio")

    cantiere = db.query(Site).filter(Site.id == cantiere_id).first()
    if not cantiere:
        raise HTTPException(status_code=404, detail="Cantiere non trovato")

    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    filters = [
        MagazzinoMovimento.cantiere_id == cantiere_id,
        MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
    ]
    if parsed_from:
        filters.append(
            MagazzinoMovimento.created_at >= datetime.combine(parsed_from, time.min)
        )
    if parsed_to:
        filters.append(
            MagazzinoMovimento.created_at <= datetime.combine(parsed_to, time.max)
        )

    total_rows = db.query(func.count(MagazzinoMovimento.id)).filter(*filters).scalar() or 0
    total_quantity = (
        db.query(func.coalesce(func.sum(MagazzinoMovimento.quantita), 0.0))
        .filter(*filters)
        .scalar()
    )
    items = (
        db.query(
            MagazzinoItem.codice,
            MagazzinoItem.nome,
            func.coalesce(func.sum(MagazzinoMovimento.quantita), 0.0).label("totale"),
        )
        .join(MagazzinoMovimento, MagazzinoMovimento.item_id == MagazzinoItem.id)
        .filter(*filters)
        .group_by(MagazzinoItem.id)
        .order_by(func.sum(MagazzinoMovimento.quantita).desc(), MagazzinoItem.nome.asc())
        .all()
    )

    if export == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Codice", "Nome", "Totale scaricato"])
        for codice, nome, totale in items:
            writer.writerow([codice or "", nome or "", totale])
        filename = f"report_consumi_{cantiere_id}_{datetime.now().strftime('%Y%m%d')}.csv"
        response = Response(output.getvalue(), media_type="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render_template(
        templates,
        request,
        "manager/magazzino/report_consumi.html",
        {
            "request": request,
            "user": current_user,
            "cantiere": cantiere,
            "date_from": parsed_from,
            "date_to": parsed_to,
            "total_rows": total_rows,
            "total_quantity": total_quantity,
            "items": items,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino/categorie",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_list",
)
def manager_magazzino_categorie_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categorie, _, _ = _load_categorie(
        db,
        include_inactive=True,
        include_fallback=False,
    )
    active_ids = [categoria.id for categoria in categorie if categoria.attiva]
    first_active_id = active_ids[0] if active_ids else None
    last_active_id = active_ids[-1] if active_ids else None
    return render_template(
        templates,
        request,
        "manager/magazzino/categorie_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie,
            "first_active_id": first_active_id,
            "last_active_id": last_active_id,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino/categorie/nuova",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_new",
)
def manager_magazzino_categorie_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    return render_template(
        templates,
        request,
        "manager/magazzino/categorie_form.html",
        {
            "request": request,
            "user": current_user,
            "categoria": None,
            "form_action": "manager_magazzino_categorie_create",
            "title": "Nuova macro categoria",
            "color_options": CATEGORIA_COLOR_OPTIONS,
            "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
            "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
        },
        None,
        current_user,
    )


@router.post(
    "/manager/magazzino/categorie/nuova",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_create",
)
def manager_magazzino_categorie_create(
    request: Request,
    nome: str = Form(...),
    ordine: str | None = Form("0"),
    icon: str | None = Form(""),
    color: str | None = Form(""),
    attiva: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    nome_value = nome.strip()
    if not nome_value:
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": None,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": "Il nome della categoria è obbligatorio.",
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    existing = (
        db.query(MagazzinoCategoria)
        .filter(func.lower(MagazzinoCategoria.nome) == nome_value.lower())
        .first()
    )
    if existing:
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": None,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": "Esiste già una categoria con questo nome.",
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    try:
        ordine_value = int(ordine or 0)
    except ValueError:
        ordine_value = 0
    try:
        icon_value, color_value = _normalize_categoria_fields(icon, color)
    except ValueError as exc:
        categoria_preview = SimpleNamespace(
            nome=nome_value,
            ordine=ordine_value,
            attiva=attiva,
            icon=icon,
            color=color,
        )
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria_preview,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": str(exc),
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    base_slug = _slugify(nome_value)
    slug = _ensure_unique_slug(db, base_slug)
    try:
        categoria = MagazzinoCategoria(
            nome=nome_value,
            slug=slug,
            ordine=ordine_value,
            attiva=attiva,
            icon=icon_value or DEFAULT_CATEGORIA_ICON,
            color=color_value or DEFAULT_CATEGORIA_COLOR,
        )
        db.add(categoria)
        db.flush()
        _log_audit(
            db,
            current_user,
            "CATEGORIA_CREATE",
            "MagazzinoCategoria",
            categoria.id,
            {
                "nome": categoria.nome,
                "ordine": categoria.ordine,
                "attiva": categoria.attiva,
                "icon": categoria.icon,
                "color": categoria.color,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except Exception:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": None,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": _magazzino_error_message(lang, "operazione_fallita"),
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/categorie/{categoria_id}/modifica",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_edit",
)
def manager_magazzino_categorie_edit(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id)
        .first()
    )
    if not categoria:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_categorie_list"),
            status_code=303,
        )
    return render_template(
        templates,
        request,
        "manager/magazzino/categorie_form.html",
        {
            "request": request,
            "user": current_user,
            "categoria": categoria,
            "form_action": "manager_magazzino_categorie_update",
            "title": "Modifica macro categoria",
            "color_options": CATEGORIA_COLOR_OPTIONS,
            "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
            "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
        },
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/categorie/{categoria_id}/modifica",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_update",
)
def manager_magazzino_categorie_update(
    categoria_id: int,
    request: Request,
    nome: str = Form(...),
    ordine: str | None = Form("0"),
    icon: str | None = Form(""),
    color: str | None = Form(""),
    attiva: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id)
        .first()
    )
    if not categoria:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_categorie_list"),
            status_code=303,
        )
    nome_value = nome.strip()
    if not nome_value:
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": "Il nome della categoria è obbligatorio.",
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    existing = (
        db.query(MagazzinoCategoria)
        .filter(
            func.lower(MagazzinoCategoria.nome) == nome_value.lower(),
            MagazzinoCategoria.id != categoria.id,
        )
        .first()
    )
    if existing:
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": "Esiste già una categoria con questo nome.",
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    try:
        ordine_value = int(ordine or 0)
    except ValueError:
        ordine_value = categoria.ordine or 0
    try:
        icon_value, color_value = _normalize_categoria_fields(icon, color)
    except ValueError as exc:
        categoria.icon = icon
        categoria.color = color
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": str(exc),
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    if categoria.nome != nome_value:
        base_slug = _slugify(nome_value)
        categoria.slug = _ensure_unique_slug(db, base_slug, exclude_id=categoria.id)
    categoria.nome = nome_value
    categoria.ordine = ordine_value
    categoria.attiva = attiva
    categoria.icon = icon_value or DEFAULT_CATEGORIA_ICON
    categoria.color = color_value or DEFAULT_CATEGORIA_COLOR
    try:
        db.add(categoria)
        _log_audit(
            db,
            current_user,
            "CATEGORIA_EDIT",
            "MagazzinoCategoria",
            categoria.id,
            {
                "nome": categoria.nome,
                "ordine": categoria.ordine,
                "attiva": categoria.attiva,
                "icon": categoria.icon,
                "color": categoria.color,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except Exception:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": _magazzino_error_message(lang, "operazione_fallita"),
                "color_options": CATEGORIA_COLOR_OPTIONS,
                "default_categoria_icon": DEFAULT_CATEGORIA_ICON,
                "default_categoria_color": DEFAULT_CATEGORIA_COLOR,
            },
            db,
            current_user,
        )
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/categorie/{categoria_id}/disattiva",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_disable",
)
def manager_magazzino_categorie_disable(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id)
        .first()
    )
    if categoria:
        categoria.attiva = False
        db.add(categoria)
        db.commit()
        _invalidate_magazzino_cache()
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/categorie/{categoria_id}/toggle",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_toggle",
)
def manager_magazzino_categorie_toggle(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id)
        .first()
    )
    if categoria:
        categoria.attiva = not categoria.attiva
        db.add(categoria)
        _log_audit(
            db,
            current_user,
            "CATEGORIA_TOGGLE",
            "MagazzinoCategoria",
            categoria.id,
            {
                "nome": categoria.nome,
                "attiva": categoria.attiva,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/categorie/{categoria_id}/su",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_up",
)
def manager_magazzino_categorie_up(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id, MagazzinoCategoria.attiva.is_(True))
        .first()
    )
    if categoria:
        _swap_categoria_order(db, categoria, "su")
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/categorie/{categoria_id}/giu",
    response_class=HTMLResponse,
    name="manager_magazzino_categorie_down",
)
def manager_magazzino_categorie_down(
    categoria_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    categoria = (
        db.query(MagazzinoCategoria)
        .filter(MagazzinoCategoria.id == categoria_id, MagazzinoCategoria.attiva.is_(True))
        .first()
    )
    if categoria:
        _swap_categoria_order(db, categoria, "giu")
    return RedirectResponse(
        url=request.url_for("manager_magazzino_categorie_list"),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/nuovo",
    response_class=HTMLResponse,
    name="manager_magazzino_new",
)
def manager_magazzino_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
    db: Session = Depends(get_db),
):
    ensure_magazzino_manager(current_user)
    categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
        db,
        include_inactive=False,
        include_fallback=False,
    )
    categoria_param = request.query_params.get("categoria_id")
    parsed_categoria_id = _parse_categoria_id(categoria_param)
    valid_ids = {categoria.id for categoria in categorie if categoria.id is not None}
    if parsed_categoria_id not in valid_ids:
        parsed_categoria_id = fallback_categoria_id
    return render_template(
        templates,
        request,
        "manager/magazzino/item_new.html",
        {
            "request": request,
            "user": current_user,
            "item": None,
            "categorie": categorie,
            "fallback_categoria": fallback_categoria,
            "default_categoria_id": parsed_categoria_id,
            "form_action": "manager_magazzino_create",
            "title": "Nuovo articolo",
        },
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/nuovo",
    response_class=HTMLResponse,
    name="manager_magazzino_create",
)
def manager_magazzino_create(
    request: Request,
    nome: str = Form(...),
    codice: str = Form(...),
    descrizione: str = Form(""),
    categoria_id: str | None = Form(None),
    quantita_disponibile: str | None = Form(""),
    soglia_minima: str | None = Form(""),
    attivo: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    item = MagazzinoItem(
        nome=nome.strip(),
        codice=codice.strip(),
        descrizione=(descrizione or "").strip() or None,
        categoria_id=_parse_categoria_id(categoria_id),
        quantita_disponibile=_parse_float(quantita_disponibile) or 0.0,
        soglia_minima=_parse_float(soglia_minima),
        attivo=attivo,
    )
    db.add(item)
    db.flush()

    _log_audit(
        db,
        current_user,
        "ITEM_CREATE",
        "MagazzinoItem",
        item.id,
        {
            "nome": item.nome,
            "codice": item.codice,
            "quantita_iniziale": item.quantita_disponibile,
            "categoria_id": item.categoria_id,
        },
    )

    if item.quantita_disponibile and item.quantita_disponibile > 0:
        movimento = MagazzinoMovimento(
            item_id=item.id,
            tipo=MagazzinoMovimentoTipoEnum.carico,
            quantita=item.quantita_disponibile,
            creato_da_user_id=current_user.id,
            note="Carico iniziale",
        )
        db.add(movimento)
        db.flush()
        _log_audit(
            db,
            current_user,
            "STOCK_CARICO",
            "MagazzinoMovimento",
            movimento.id,
            {
                "item_id": item.id,
                "codice": item.codice,
                "quantita": item.quantita_disponibile,
                "note": "Carico iniziale",
            },
        )
    db.commit()
    _invalidate_magazzino_cache()

    return RedirectResponse(
        url=f"{request.url_for('manager_magazzino_list')}?ok=duplicato",
        status_code=303,
    )


@router.get(
    "/manager/magazzino/{item_id}/modifica",
    response_class=HTMLResponse,
    name="manager_magazzino_edit",
)
def manager_magazzino_edit(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )
    categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
        db,
        include_inactive=False,
        include_fallback=False,
    )

    return render_template(
        templates,
        request,
        "manager/magazzino/item_edit.html",
        {
            "request": request,
            "user": current_user,
            "item": item,
            "categorie": categorie,
            "fallback_categoria": fallback_categoria,
            "default_categoria_id": fallback_categoria_id,
            "form_action": "manager_magazzino_update",
            "title": "Modifica articolo",
        },
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/{item_id}/modifica",
    response_class=HTMLResponse,
    name="manager_magazzino_update",
)
def manager_magazzino_update(
    item_id: int,
    request: Request,
    nome: str = Form(...),
    codice: str = Form(...),
    descrizione: str = Form(""),
    categoria_id: str | None = Form(None),
    quantita_disponibile: str | None = Form(""),
    soglia_minima: str | None = Form(""),
    attivo: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )

    try:
        quantita_precedente = item.quantita_disponibile or 0.0
        nuova_quantita = _parse_float(quantita_disponibile) or 0.0
        if nuova_quantita < 0:
            raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))

        item.nome = nome.strip()
        item.codice = codice.strip()
        item.descrizione = (descrizione or "").strip() or None
        item.categoria_id = _parse_categoria_id(categoria_id)
        item.quantita_disponibile = nuova_quantita
        item.soglia_minima = _parse_float(soglia_minima)
        item.attivo = attivo

        db.add(item)
        differenza = (item.quantita_disponibile or 0.0) - quantita_precedente
        if abs(differenza) > 0:
            movimento = MagazzinoMovimento(
                item_id=item.id,
                tipo=MagazzinoMovimentoTipoEnum.carico
                if differenza > 0
                else MagazzinoMovimentoTipoEnum.scarico,
                quantita=abs(differenza),
                creato_da_user_id=current_user.id,
                note="Rettifica quantità",
            )
            db.add(movimento)
            db.flush()
            _log_audit(
                db,
                current_user,
                "STOCK_RETTIFICA",
                "MagazzinoItem",
                item.id,
                {
                    "codice": item.codice,
                    "quantita_precedente": quantita_precedente,
                    "quantita_nuova": item.quantita_disponibile,
                    "differenza": differenza,
                },
            )
            _log_audit(
                db,
                current_user,
                "STOCK_RETTIFICA",
                "MagazzinoMovimento",
                movimento.id,
                {
                    "item_id": item.id,
                    "codice": item.codice,
                    "quantita": abs(differenza),
                    "note": "Rettifica quantità",
                },
            )
        _log_audit(
            db,
            current_user,
            "ITEM_EDIT",
            "MagazzinoItem",
            item.id,
            {
                "nome": item.nome,
                "codice": item.codice,
                "quantita": item.quantita_disponibile,
                "categoria_id": item.categoria_id,
                "attivo": item.attivo,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except ValueError as exc:
        db.rollback()
        categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
            db,
            include_inactive=False,
            include_fallback=False,
        )
        return render_template(
            templates,
            request,
            "manager/magazzino/item_edit.html",
            {
                "request": request,
                "user": current_user,
                "item": item,
                "categorie": categorie,
                "fallback_categoria": fallback_categoria,
                "default_categoria_id": fallback_categoria_id,
                "form_action": "manager_magazzino_update",
                "title": "Modifica articolo",
                "error_message": str(exc),
            },
            db,
            current_user,
        )
    except Exception:
        db.rollback()
        categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
            db,
            include_inactive=False,
            include_fallback=False,
        )
        return render_template(
            templates,
            request,
            "manager/magazzino/item_edit.html",
            {
                "request": request,
                "user": current_user,
                "item": item,
                "categorie": categorie,
                "fallback_categoria": fallback_categoria,
                "default_categoria_id": fallback_categoria_id,
                "form_action": "manager_magazzino_update",
                "title": "Modifica articolo",
                "error_message": _magazzino_error_message(lang, "operazione_fallita"),
            },
            db,
            current_user,
        )

    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/items/{item_id}/duplica",
    response_class=HTMLResponse,
    name="manager_magazzino_duplicate",
)
def manager_magazzino_duplicate(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    item = (
        db.query(MagazzinoItem)
        .options(joinedload(MagazzinoItem.categoria))
        .filter(MagazzinoItem.id == item_id)
        .first()
    )
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )
    return render_template(
        templates,
        request,
        "manager/magazzino/item_duplicate.html",
        {
            "request": request,
            "user": current_user,
            "item": item,
            "error_message": None,
            "title": "Duplica articolo",
        },
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/items/{item_id}/duplica",
    response_class=HTMLResponse,
    name="manager_magazzino_duplicate_create",
)
def manager_magazzino_duplicate_create(
    item_id: int,
    request: Request,
    codice: str = Form(...),
    quantita_iniziale: str | None = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    item = (
        db.query(MagazzinoItem)
        .options(joinedload(MagazzinoItem.categoria))
        .filter(MagazzinoItem.id == item_id)
        .first()
    )
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )
    codice_value = codice.strip()
    if not codice_value:
        return render_template(
            templates,
            request,
            "manager/magazzino/item_duplicate.html",
            {
                "request": request,
                "user": current_user,
                "item": item,
                "error_message": "Il codice articolo è obbligatorio.",
                "title": "Duplica articolo",
            },
            db,
            current_user,
        )
    existing = (
        db.query(MagazzinoItem)
        .filter(func.lower(MagazzinoItem.codice) == codice_value.lower())
        .first()
    )
    if existing:
        return render_template(
            templates,
            request,
            "manager/magazzino/item_duplicate.html",
            {
                "request": request,
                "user": current_user,
                "item": item,
                "error_message": "Esiste già un articolo con questo codice.",
                "title": "Duplica articolo",
            },
            db,
            current_user,
        )
    quantita_value = _parse_float(quantita_iniziale) or 0.0
    nuovo_item = MagazzinoItem(
        nome=item.nome,
        codice=codice_value,
        descrizione=item.descrizione,
        unita_misura=item.unita_misura,
        categoria_id=item.categoria_id,
        quantita_disponibile=quantita_value,
        soglia_minima=item.soglia_minima,
        attivo=item.attivo,
        preferito=False,
    )
    db.add(nuovo_item)
    db.flush()

    _log_audit(
        db,
        current_user,
        "ITEM_DUPLICATE",
        "MagazzinoItem",
        nuovo_item.id,
        {
            "item_origine_id": item.id,
            "nome": nuovo_item.nome,
            "codice": nuovo_item.codice,
            "quantita_iniziale": nuovo_item.quantita_disponibile,
            "categoria_id": nuovo_item.categoria_id,
        },
    )

    if nuovo_item.quantita_disponibile and nuovo_item.quantita_disponibile > 0:
        movimento = MagazzinoMovimento(
            item_id=nuovo_item.id,
            tipo=MagazzinoMovimentoTipoEnum.carico,
            quantita=nuovo_item.quantita_disponibile,
            creato_da_user_id=current_user.id,
            note="Carico iniziale",
        )
        db.add(movimento)
        db.flush()
        _log_audit(
            db,
            current_user,
            "STOCK_CARICO",
            "MagazzinoMovimento",
            movimento.id,
            {
                "item_id": nuovo_item.id,
                "codice": nuovo_item.codice,
                "quantita": nuovo_item.quantita_disponibile,
                "note": "Carico iniziale",
            },
        )
    db.commit()
    _invalidate_magazzino_cache()

    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/items/{item_id}/preferito-toggle",
    response_class=HTMLResponse,
    name="manager_magazzino_preferito_toggle",
)
def manager_magazzino_preferito_toggle(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if not item:
        return RedirectResponse(
            url=f"{request.url_for('manager_magazzino_list')}?err=item_non_trovato",
            status_code=303,
        )
    item.preferito = not item.preferito
    db.add(item)
    _log_audit(
        db,
        current_user,
        "ITEM_TOGGLE_PREFERITO",
        "MagazzinoItem",
        item.id,
        {"preferito": item.preferito},
    )
    db.commit()
    _invalidate_magazzino_cache()
    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/scarico",
    response_class=HTMLResponse,
    name="manager_magazzino_scarico",
)
def manager_magazzino_scarico(
    request: Request,
    item_id: int = Form(...),
    quantita: str = Form(...),
    cantiere_id: int | None = Form(None),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    try:
        item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
        if not item:
            raise ValueError(_magazzino_error_message(lang, "item_non_trovato"))

        quantita_valore = _parse_float(quantita)
        if not quantita_valore or quantita_valore <= 0:
            raise ValueError(_magazzino_error_message(lang, "quantita_non_valida"))

        quantita_attuale = item.quantita_disponibile or 0.0
        if quantita_valore > quantita_attuale:
            raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))

        item.quantita_disponibile = quantita_attuale - quantita_valore

        db.add(item)
        movimento = MagazzinoMovimento(
            item_id=item.id,
            tipo=MagazzinoMovimentoTipoEnum.scarico,
            quantita=quantita_valore,
            cantiere_id=cantiere_id,
            creato_da_user_id=current_user.id,
            note=(note or "").strip() or None,
        )
        db.add(movimento)
        db.flush()
        _log_audit(
            db,
            current_user,
            "STOCK_SCARICO",
            "MagazzinoMovimento",
            movimento.id,
            {
                "item_id": item.id,
                "codice": item.codice,
                "quantita": quantita_valore,
                "cantiere_id": cantiere_id,
                "note": (note or "").strip() or None,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except ValueError as exc:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=str(exc),
        )
    except Exception:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=_magazzino_error_message(lang, "operazione_fallita"),
        )

    return RedirectResponse(
        url=f"{request.url_for('manager_magazzino_list')}?ok=scarico",
        status_code=303,
    )


@router.post(
    "/manager/magazzino/items/{item_id}/carico-rapido",
    response_class=HTMLResponse,
    name="manager_magazzino_carico_rapido",
)
def manager_magazzino_carico_rapido(
    item_id: int,
    request: Request,
    quantita: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    try:
        item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
        if not item:
            raise ValueError(_magazzino_error_message(lang, "item_non_trovato"))

        quantita_valore = _parse_float(quantita)
        if not quantita_valore or quantita_valore <= 0:
            raise ValueError(_magazzino_error_message(lang, "quantita_non_valida"))

        item.quantita_disponibile = (item.quantita_disponibile or 0.0) + quantita_valore
        db.add(item)
        movimento = MagazzinoMovimento(
            item_id=item.id,
            tipo=MagazzinoMovimentoTipoEnum.carico,
            quantita=quantita_valore,
            creato_da_user_id=current_user.id,
            note=(note or "").strip() or None,
        )
        db.add(movimento)
        db.flush()
        _log_audit(
            db,
            current_user,
            "STOCK_CARICO",
            "MagazzinoMovimento",
            movimento.id,
            {
                "item_id": item.id,
                "codice": item.codice,
                "quantita": quantita_valore,
                "note": (note or "").strip() or None,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except ValueError as exc:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=str(exc),
        )
    except Exception:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=_magazzino_error_message(lang, "operazione_fallita"),
        )

    return RedirectResponse(
        url=f"{request.url_for('manager_magazzino_list')}?ok=carico",
        status_code=303,
    )


@router.post(
    "/manager/magazzino/items/{item_id}/scarico-rapido",
    response_class=HTMLResponse,
    name="manager_magazzino_scarico_rapido",
)
def manager_magazzino_scarico_rapido(
    item_id: int,
    request: Request,
    quantita: str = Form(...),
    note: str = Form(""),
    cantiere_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    try:
        item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
        if not item:
            raise ValueError(_magazzino_error_message(lang, "item_non_trovato"))

        quantita_valore = _parse_float(quantita)
        if not quantita_valore or quantita_valore <= 0:
            raise ValueError(_magazzino_error_message(lang, "quantita_non_valida"))

        quantita_attuale = item.quantita_disponibile or 0.0
        if quantita_valore > quantita_attuale:
            raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))

        item.quantita_disponibile = quantita_attuale - quantita_valore
        db.add(item)
        movimento = MagazzinoMovimento(
            item_id=item.id,
            tipo=MagazzinoMovimentoTipoEnum.scarico,
            quantita=quantita_valore,
            cantiere_id=cantiere_id,
            creato_da_user_id=current_user.id,
            note=(note or "").strip() or None,
        )
        db.add(movimento)
        db.flush()
        _log_audit(
            db,
            current_user,
            "STOCK_SCARICO",
            "MagazzinoMovimento",
            movimento.id,
            {
                "item_id": item.id,
                "codice": item.codice,
                "quantita": quantita_valore,
                "cantiere_id": cantiere_id,
                "note": (note or "").strip() or None,
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except ValueError as exc:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=str(exc),
        )
    except Exception:
        db.rollback()
        return _render_magazzino_items_list(
            request,
            db,
            current_user,
            error_message=_magazzino_error_message(lang, "operazione_fallita"),
        )

    return RedirectResponse(
        url=f"{request.url_for('manager_magazzino_list')}?ok=scarico",
        status_code=303,
    )


@router.post(
    "/manager/magazzino/{item_id}/elimina",
    response_class=HTMLResponse,
    name="manager_magazzino_delete",
)
def manager_magazzino_delete(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    if not has_perm(current_user, "records.delete"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if item:
        item.attivo = False
        db.add(item)
        db.commit()
        _invalidate_magazzino_cache()

    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
        status_code=303,
    )


@router.get(
    "/manager/magazzino/richieste",
    response_class=HTMLResponse,
    name="manager_magazzino_richieste",
)
def manager_magazzino_richieste(
    request: Request,
    stato: str | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    page, per_page = _normalize_pagination(page, per_page)
    stato_filtro = None
    if stato and stato.lower() != "tutte":
        stato_filtro = _parse_status(stato) or MagazzinoRichiestaStatusEnum.in_attesa
    elif not stato:
        stato_filtro = MagazzinoRichiestaStatusEnum.in_attesa

    query = db.query(MagazzinoRichiesta).options(
        selectinload(MagazzinoRichiesta.righe).selectinload(MagazzinoRichiestaRiga.item),
        joinedload(MagazzinoRichiesta.richiesto_da),
        joinedload(MagazzinoRichiesta.cantiere),
    )
    if stato_filtro:
        query = query.filter(MagazzinoRichiesta.stato == stato_filtro)

    total_count = query.count()
    total_pages = max(1, ceil(total_count / per_page))
    richieste = (
        query.order_by(MagazzinoRichiesta.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return render_template(
        templates,
        request,
        "manager/magazzino/richieste_list.html",
        {
            "request": request,
            "user": current_user,
            "richieste": richieste,
            "stato_filtro": stato_filtro,
            "stati": list(MagazzinoRichiestaStatusEnum),
            "oggi": date.today(),
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
        db,
        current_user,
    )


@router.get(
    "/manager/magazzino/richieste/{richiesta_id}",
    response_class=HTMLResponse,
    name="manager_magazzino_richiesta_detail",
)
def manager_magazzino_richiesta_detail(
    richiesta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    richiesta = (
        db.query(MagazzinoRichiesta)
        .options(
            selectinload(MagazzinoRichiesta.righe).selectinload(
                MagazzinoRichiestaRiga.item
            ),
            joinedload(MagazzinoRichiesta.richiesto_da),
            joinedload(MagazzinoRichiesta.gestito_da),
            joinedload(MagazzinoRichiesta.cantiere),
        )
        .filter(MagazzinoRichiesta.id == richiesta_id)
        .first()
    )
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
        )

    return render_template(
        templates,
        request,
        "manager/magazzino/richiesta_detail.html",
        {"request": request, "user": current_user, "richiesta": richiesta},
        db,
        current_user,
    )


@router.post(
    "/manager/magazzino/richieste/{richiesta_id}/approva",
    response_class=HTMLResponse,
    name="manager_magazzino_richiesta_approva",
)
def manager_magazzino_richiesta_approva(
    richiesta_id: int,
    request: Request,
    risposta_manager: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    richiesta = (
        db.query(MagazzinoRichiesta)
        .options(
            joinedload(MagazzinoRichiesta.righe).joinedload(
                MagazzinoRichiestaRiga.item
            )
        )
        .filter(MagazzinoRichiesta.id == richiesta_id)
        .first()
    )
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
        )

    try:
        for riga in richiesta.righe:
            if riga.item is None:
                raise ValueError("Item non disponibile")
            if riga.item.quantita_disponibile < riga.quantita_richiesta:
                raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))

        richiesta.stato = MagazzinoRichiestaStatusEnum.approvata
        richiesta.risposta_manager = (risposta_manager or "").strip() or None
        richiesta.gestito_da_user_id = current_user.id
        richiesta.gestito_at = datetime.utcnow()
        richiesta.letto_da_richiedente = False

        db.add(richiesta)
        _log_audit(
            db,
            current_user,
            "RICHIESTA_APPROVATA",
            "MagazzinoRichiesta",
            richiesta.id,
            {
                "risposta_manager": richiesta.risposta_manager,
                "righe": len(richiesta.righe),
            },
        )
        db.commit()
        _invalidate_magazzino_cache()
    except ValueError as exc:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": str(exc),
            },
            db,
            current_user,
        )
    except Exception:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": _magazzino_error_message(lang, "operazione_fallita"),
            },
            db,
            current_user,
        )

    return RedirectResponse(
        url=request.url_for(
            "manager_magazzino_richiesta_detail", richiesta_id=richiesta.id
        ),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/richieste/{richiesta_id}/evadi",
    response_class=HTMLResponse,
    name="manager_magazzino_richiesta_evadi",
)
async def manager_magazzino_richiesta_evadi(
    richiesta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    richiesta = (
        db.query(MagazzinoRichiesta)
        .options(
            joinedload(MagazzinoRichiesta.righe).joinedload(
                MagazzinoRichiestaRiga.item
            )
        )
        .filter(MagazzinoRichiesta.id == richiesta_id)
        .first()
    )
    if not richiesta:
        return RedirectResponse(
            url=f"{request.url_for('manager_magazzino_richieste')}?err=richiesta_non_trovata",
            status_code=303,
        )

    if richiesta.stato not in (
        MagazzinoRichiestaStatusEnum.approvata,
        MagazzinoRichiestaStatusEnum.parziale,
    ):
        return RedirectResponse(
            url=(
                request.url_for(
                    "manager_magazzino_richiesta_detail", richiesta_id=richiesta.id
                )
                + "?err=stato_non_approvato"
            ),
            status_code=303,
        )

    try:
        form_data = await request.form()
        righe_quantita = {}
        item_totals: dict[int, float] = {}

        for riga in richiesta.righe:
            if riga.quantita_richiesta is None or riga.quantita_richiesta <= 0:
                raise HTTPException(
                    status_code=400, detail="Quantità richiesta non valida"
                )
            if riga.item is None or not riga.item.attivo:
                raise HTTPException(status_code=400, detail="Item non disponibile")

            quantita_evasa = riga.quantita_evasa or 0.0
            residua = max(0.0, riga.quantita_richiesta - quantita_evasa)
            raw_value = form_data.get(f"quantita_da_evadere_{riga.id}")
            if raw_value not in (None, ""):
                quantita_da_evadere = _parse_float(str(raw_value))
                if quantita_da_evadere is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Quantità da evadere non valida per {riga.item.nome}",
                    )
            else:
                quantita_da_evadere = residua

            if quantita_da_evadere < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Quantità da evadere non valida per {riga.item.nome}",
                )
            if quantita_da_evadere > residua:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Quantità da evadere superiore al residuo per "
                        f"{riga.item.nome} (residuo {residua})"
                    ),
                )

            righe_quantita[riga.id] = quantita_da_evadere
            if quantita_da_evadere > 0:
                item_totals[riga.item.id] = item_totals.get(riga.item.id, 0.0) + quantita_da_evadere

        for item_id, totale in item_totals.items():
            item = next(
                (riga.item for riga in richiesta.righe if riga.item and riga.item.id == item_id),
                None,
            )
            quantita_disponibile = item.quantita_disponibile if item else 0.0
            if quantita_disponibile < totale:
                raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))

        if not any(quantita > 0 for quantita in righe_quantita.values()):
            raise HTTPException(
                status_code=400, detail="Nessuna quantità da evadere"
            )

        for riga in richiesta.righe:
            quantita_da_evadere = righe_quantita.get(riga.id, 0.0)
            if quantita_da_evadere <= 0:
                continue
            quantita_disponibile = riga.item.quantita_disponibile or 0.0
            if quantita_disponibile < quantita_da_evadere:
                raise ValueError(_magazzino_error_message(lang, "quantita_insufficiente"))
            riga.item.quantita_disponibile = (
                quantita_disponibile - quantita_da_evadere
            )
            riga.quantita_evasa = (riga.quantita_evasa or 0.0) + quantita_da_evadere
            db.add(riga.item)
            db.add(riga)
            movimento = MagazzinoMovimento(
                item_id=riga.item.id,
                tipo=MagazzinoMovimentoTipoEnum.scarico,
                quantita=quantita_da_evadere,
                cantiere_id=richiesta.cantiere_id,
                creato_da_user_id=current_user.id,
                riferimento_richiesta_id=richiesta.id,
            )
            db.add(movimento)
            db.flush()
            _log_audit(
                db,
                current_user,
                "STOCK_SCARICO",
                "MagazzinoMovimento",
                movimento.id,
                {
                    "item_id": riga.item.id,
                    "codice": riga.item.codice,
                    "quantita": quantita_da_evadere,
                    "cantiere_id": richiesta.cantiere_id,
                    "richiesta_id": richiesta.id,
                },
            )

        tutte_evase = all(
            (riga.quantita_evasa or 0.0) >= riga.quantita_richiesta
            for riga in richiesta.righe
        )
        almeno_una_evasa = any(
            (riga.quantita_evasa or 0.0) > 0 for riga in richiesta.righe
        )

        if tutte_evase:
            richiesta.stato = MagazzinoRichiestaStatusEnum.evasa
            audit_action = "RICHIESTA_EVASA"
        elif almeno_una_evasa:
            richiesta.stato = MagazzinoRichiestaStatusEnum.parziale
            audit_action = "RICHIESTA_EVASA_PARZIALE"
        richiesta.gestito_da_user_id = current_user.id
        richiesta.gestito_at = datetime.utcnow()
        richiesta.letto_da_richiedente = False
        db.add(richiesta)
        _log_audit(
            db,
            current_user,
            audit_action,
            "MagazzinoRichiesta",
            richiesta.id,
            {
                "righe": len(richiesta.righe),
                "cantiere_id": richiesta.cantiere_id,
            },
        )

        db.commit()
        _invalidate_magazzino_cache()
    except HTTPException as exc:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": exc.detail,
            },
            db,
            current_user,
            status_code=exc.status_code,
        )
    except ValueError as exc:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": str(exc),
            },
            db,
            current_user,
            status_code=400,
        )
    except Exception:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": "Errore durante l'evasione della richiesta.",
            },
            db,
            current_user,
            status_code=500,
        )

    return RedirectResponse(
        url=request.url_for(
            "manager_magazzino_richiesta_detail", richiesta_id=richiesta.id
        ),
        status_code=303,
    )


@router.post(
    "/manager/magazzino/richieste/{richiesta_id}/rifiuta",
    response_class=HTMLResponse,
    name="manager_magazzino_richiesta_rifiuta",
)
def manager_magazzino_richiesta_rifiuta(
    richiesta_id: int,
    request: Request,
    risposta_manager: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    lang = request.cookies.get("lang", "it")
    richiesta = db.query(MagazzinoRichiesta).filter(MagazzinoRichiesta.id == richiesta_id).first()
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
        )

    try:
        richiesta.stato = MagazzinoRichiestaStatusEnum.rifiutata
        richiesta.risposta_manager = (risposta_manager or "").strip() or None
        richiesta.gestito_da_user_id = current_user.id
        richiesta.gestito_at = datetime.utcnow()
        richiesta.letto_da_richiedente = False

        db.add(richiesta)
        _log_audit(
            db,
            current_user,
            "RICHIESTA_RIFIUTATA",
            "MagazzinoRichiesta",
            richiesta.id,
            {"risposta_manager": richiesta.risposta_manager},
        )
        db.commit()
        _invalidate_magazzino_cache()
    except Exception:
        db.rollback()
        return render_template(
            templates,
            request,
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": _magazzino_error_message(lang, "operazione_fallita"),
            },
            db,
            current_user,
        )

    return RedirectResponse(
        url=request.url_for(
            "manager_magazzino_richiesta_detail", richiesta_id=richiesta.id
        ),
        status_code=303,
    )
