from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import (
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    MagazzinoRichiesta,
    MagazzinoRichiestaRiga,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    Site,
    User,
)


templates = Jinja2Templates(directory="templates")
router = APIRouter(tags=["magazzino"])


def ensure_caposquadra_or_manager(user: User) -> None:
    if user.role not in (RoleEnum.admin, RoleEnum.manager, RoleEnum.caposquadra):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def ensure_magazzino_manager(user: User) -> None:
    if user.role == RoleEnum.admin:
        return
    if user.role == RoleEnum.manager and user.is_magazzino_manager:
        return
    raise HTTPException(status_code=403, detail="Permessi insufficienti")


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


def _order_categorie_for_display(
    categorie: list[MagazzinoCategoria | SimpleNamespace],
) -> list[MagazzinoCategoria | SimpleNamespace]:
    fallback = [categoria for categoria in categorie if categoria.id is None]
    others = [categoria for categoria in categorie if categoria.id is not None]
    return [*others, *fallback]


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
    query = db.query(MagazzinoItem).filter(MagazzinoItem.attivo.is_(True))
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
            MagazzinoItem.nome.asc(),
        )
        .all()
    )
    items_by_categoria = _group_items_by_categoria(
        items,
        [categoria for categoria in categorie if isinstance(categoria, MagazzinoCategoria)],
        fallback_categoria_id,
    )
    categorie_display = _order_categorie_for_display(categorie)
    filters = {
        "q": q_value,
        "categoria": categoria or "",
        "sotto_soglia": sotto_soglia == 1,
        "esauriti": esauriti == 1,
    }
    return templates.TemplateResponse(
        "capo/magazzino/items_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie_display,
            "fallback_categoria": fallback_categoria,
            "items_by_categoria": items_by_categoria,
            "items_count": len(items),
            "filters": filters,
        },
    )


@router.get(
    "/capo/magazzino/richieste",
    response_class=HTMLResponse,
    name="capo_magazzino_richieste",
)
def capo_magazzino_richieste(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_caposquadra_or_manager(current_user)
    richieste = (
        db.query(MagazzinoRichiesta)
        .options(
            joinedload(MagazzinoRichiesta.righe).joinedload(
                MagazzinoRichiestaRiga.item
            )
        )
        .filter(MagazzinoRichiesta.richiesto_da_user_id == current_user.id)
        .order_by(MagazzinoRichiesta.created_at.desc())
        .all()
    )
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
    return templates.TemplateResponse(
        "capo/magazzino/richieste_list.html",
        {
            "request": request,
            "user": current_user,
            "richieste": richieste,
            "unread_ids": set(unread_ids),
        },
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
        db.commit()

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
    return templates.TemplateResponse(
        "capo/magazzino/richieste_new.html",
        {"request": request, "user": current_user, "items": items},
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

    richiesta = MagazzinoRichiesta(
        richiesto_da_user_id=current_user.id,
        note=note.strip() or None,
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

    return RedirectResponse(
        url=request.url_for("capo_magazzino_richieste"),
        status_code=303,
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
    categorie, fallback_categoria, fallback_categoria_id = _load_categorie(
        db,
        include_inactive=False,
        include_fallback=True,
    )
    query = db.query(MagazzinoItem)
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
            MagazzinoItem.nome.asc(),
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
    filters = {
        "q": q_value,
        "categoria": categoria or "",
        "attivi": attivi == 1,
        "sotto_soglia": sotto_soglia == 1,
        "esauriti": esauriti == 1,
    }
    return templates.TemplateResponse(
        "manager/magazzino/items_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie_display,
            "fallback_categoria": fallback_categoria,
            "default_categoria_id": fallback_categoria_id,
            "items_by_categoria": items_by_categoria,
            "items_count": len(items),
            "filters": filters,
            "cantieri": cantieri,
        },
    )


@router.get(
    "/manager/magazzino/movimenti",
    response_class=HTMLResponse,
    name="manager_magazzino_movimenti",
)
def manager_magazzino_movimenti(
    request: Request,
    cantiere_id: int | None = None,
    item_id: int | None = None,
    tipo: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to)

    query = db.query(MagazzinoMovimento).options(
        joinedload(MagazzinoMovimento.item),
        joinedload(MagazzinoMovimento.cantiere),
        joinedload(MagazzinoMovimento.user),
    )
    if cantiere_id:
        query = query.filter(MagazzinoMovimento.cantiere_id == cantiere_id)
    if item_id:
        query = query.filter(MagazzinoMovimento.item_id == item_id)
    if tipo in (MagazzinoMovimentoTipoEnum.scarico.value, MagazzinoMovimentoTipoEnum.carico.value):
        query = query.filter(MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum(tipo))
    if parsed_from:
        query = query.filter(
            MagazzinoMovimento.created_at >= datetime.combine(parsed_from, time.min)
        )
    if parsed_to:
        query = query.filter(
            MagazzinoMovimento.created_at <= datetime.combine(parsed_to, time.max)
        )

    movimenti = query.order_by(MagazzinoMovimento.created_at.desc()).all()

    summary_query = db.query(
        Site,
        func.coalesce(func.sum(MagazzinoMovimento.quantita), 0.0),
    ).join(
        MagazzinoMovimento,
        MagazzinoMovimento.cantiere_id == Site.id,
    ).filter(
        MagazzinoMovimento.tipo == MagazzinoMovimentoTipoEnum.scarico,
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

    return templates.TemplateResponse(
        "manager/magazzino/movimenti_list.html",
        {
            "request": request,
            "user": current_user,
            "movimenti": movimenti,
            "cantieri": cantieri,
            "items": items,
            "tipo_options": [
                MagazzinoMovimentoTipoEnum.scarico.value,
                MagazzinoMovimentoTipoEnum.carico.value,
            ],
            "selected": {
                "cantiere_id": cantiere_id,
                "item_id": item_id,
                "tipo": tipo,
                "date_from": parsed_from.isoformat() if parsed_from else "",
                "date_to": parsed_to.isoformat() if parsed_to else "",
            },
            "totals": totals,
            "has_period_filter": bool(parsed_from or parsed_to),
        },
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
    return templates.TemplateResponse(
        "manager/magazzino/categorie_list.html",
        {
            "request": request,
            "user": current_user,
            "categorie": categorie,
            "first_active_id": first_active_id,
            "last_active_id": last_active_id,
        },
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
    return templates.TemplateResponse(
        "manager/magazzino/categorie_form.html",
        {
            "request": request,
            "user": current_user,
            "categoria": None,
            "form_action": "manager_magazzino_categorie_create",
            "title": "Nuova macro categoria",
        },
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
    attiva: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    nome_value = nome.strip()
    if not nome_value:
        return templates.TemplateResponse(
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": None,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": "Il nome della categoria è obbligatorio.",
            },
        )
    existing = (
        db.query(MagazzinoCategoria)
        .filter(func.lower(MagazzinoCategoria.nome) == nome_value.lower())
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": None,
                "form_action": "manager_magazzino_categorie_create",
                "title": "Nuova macro categoria",
                "error_message": "Esiste già una categoria con questo nome.",
            },
        )
    try:
        ordine_value = int(ordine or 0)
    except ValueError:
        ordine_value = 0
    base_slug = _slugify(nome_value)
    slug = _ensure_unique_slug(db, base_slug)
    categoria = MagazzinoCategoria(
        nome=nome_value,
        slug=slug,
        ordine=ordine_value,
        attiva=attiva,
    )
    db.add(categoria)
    db.commit()
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
    return templates.TemplateResponse(
        "manager/magazzino/categorie_form.html",
        {
            "request": request,
            "user": current_user,
            "categoria": categoria,
            "form_action": "manager_magazzino_categorie_update",
            "title": "Modifica macro categoria",
        },
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
    attiva: bool = Form(False),
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
    nome_value = nome.strip()
    if not nome_value:
        return templates.TemplateResponse(
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": "Il nome della categoria è obbligatorio.",
            },
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
        return templates.TemplateResponse(
            "manager/magazzino/categorie_form.html",
            {
                "request": request,
                "user": current_user,
                "categoria": categoria,
                "form_action": "manager_magazzino_categorie_update",
                "title": "Modifica macro categoria",
                "error_message": "Esiste già una categoria con questo nome.",
            },
        )
    try:
        ordine_value = int(ordine or 0)
    except ValueError:
        ordine_value = categoria.ordine or 0
    if categoria.nome != nome_value:
        base_slug = _slugify(nome_value)
        categoria.slug = _ensure_unique_slug(db, base_slug, exclude_id=categoria.id)
    categoria.nome = nome_value
    categoria.ordine = ordine_value
    categoria.attiva = attiva
    db.add(categoria)
    db.commit()
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
        db.commit()
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
    return templates.TemplateResponse(
        "manager/magazzino/item_new.html",
        {
            "request": request,
            "user": current_user,
            "item": None,
            "categorie": categorie,
            "fallback_categoria": fallback_categoria,
            "default_categoria_id": fallback_categoria_id,
            "form_action": "manager_magazzino_create",
            "title": "Nuovo articolo",
        },
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

    if item.quantita_disponibile and item.quantita_disponibile > 0:
        movimento = MagazzinoMovimento(
            item_id=item.id,
            tipo=MagazzinoMovimentoTipoEnum.carico,
            quantita=item.quantita_disponibile,
            user_id=current_user.id,
            note="Carico iniziale",
        )
        db.add(movimento)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
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

    return templates.TemplateResponse(
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
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )

    quantita_precedente = item.quantita_disponibile or 0.0

    item.nome = nome.strip()
    item.codice = codice.strip()
    item.descrizione = (descrizione or "").strip() or None
    item.categoria_id = _parse_categoria_id(categoria_id)
    item.quantita_disponibile = _parse_float(quantita_disponibile) or 0.0
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
            user_id=current_user.id,
            note="Rettifica quantità",
        )
        db.add(movimento)
    db.commit()

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
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if not item:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )

    quantita_valore = _parse_float(quantita)
    if not quantita_valore or quantita_valore <= 0:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_list"),
            status_code=303,
        )

    quantita_attuale = item.quantita_disponibile or 0.0
    item.quantita_disponibile = max(0.0, quantita_attuale - quantita_valore)

    db.add(item)
    movimento = MagazzinoMovimento(
        item_id=item.id,
        tipo=MagazzinoMovimentoTipoEnum.scarico,
        quantita=quantita_valore,
        cantiere_id=cantiere_id,
        user_id=current_user.id,
        note=(note or "").strip() or None,
    )
    db.add(movimento)
    db.commit()

    return RedirectResponse(
        url=request.url_for("manager_magazzino_list"),
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
    item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
    if item:
        item.attivo = False
        db.add(item)
        db.commit()

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    stato_filtro = None
    if stato and stato.lower() != "tutte":
        stato_filtro = _parse_status(stato) or MagazzinoRichiestaStatusEnum.in_attesa
    elif not stato:
        stato_filtro = MagazzinoRichiestaStatusEnum.in_attesa

    query = db.query(MagazzinoRichiesta).options(
        joinedload(MagazzinoRichiesta.righe).joinedload(MagazzinoRichiestaRiga.item),
        joinedload(MagazzinoRichiesta.richiesto_da),
    )
    if stato_filtro:
        query = query.filter(MagazzinoRichiesta.stato == stato_filtro)

    richieste = query.order_by(MagazzinoRichiesta.created_at.desc()).all()

    return templates.TemplateResponse(
        "manager/magazzino/richieste_list.html",
        {
            "request": request,
            "user": current_user,
            "richieste": richieste,
            "stato_filtro": stato_filtro,
            "stati": list(MagazzinoRichiestaStatusEnum),
        },
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
            joinedload(MagazzinoRichiesta.righe).joinedload(
                MagazzinoRichiestaRiga.item
            ),
            joinedload(MagazzinoRichiesta.richiesto_da),
            joinedload(MagazzinoRichiesta.gestito_da),
        )
        .filter(MagazzinoRichiesta.id == richiesta_id)
        .first()
    )
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
        )

    return templates.TemplateResponse(
        "manager/magazzino/richiesta_detail.html",
        {"request": request, "user": current_user, "richiesta": richiesta},
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

    for riga in richiesta.righe:
        if riga.item is None:
            raise HTTPException(status_code=400, detail="Item non disponibile")
        if riga.item.quantita_disponibile < riga.quantita_richiesta:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Quantità insufficiente per "
                    f"{riga.item.nome} (disponibile "
                    f"{riga.item.quantita_disponibile}, "
                    f"richiesta {riga.quantita_richiesta})"
                ),
            )

    richiesta.stato = MagazzinoRichiestaStatusEnum.approvata
    richiesta.risposta_manager = (risposta_manager or "").strip() or None
    richiesta.gestito_da_user_id = current_user.id
    richiesta.gestito_at = datetime.utcnow()
    richiesta.letto_da_richiedente = False

    db.add(richiesta)
    db.commit()

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
def manager_magazzino_richiesta_evadi(
    richiesta_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
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

    if richiesta.stato != MagazzinoRichiestaStatusEnum.approvata:
        raise HTTPException(
            status_code=400, detail="La richiesta non è approvata"
        )

    try:
        for riga in richiesta.righe:
            if riga.quantita_richiesta is None or riga.quantita_richiesta <= 0:
                raise HTTPException(
                    status_code=400, detail="Quantità richiesta non valida"
                )
            if riga.item is None or not riga.item.attivo:
                raise HTTPException(status_code=400, detail="Item non disponibile")
            quantita_disponibile = riga.item.quantita_disponibile or 0.0
            if quantita_disponibile < riga.quantita_richiesta:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Quantità insufficiente per "
                        f"{riga.item.nome} (disponibile "
                        f"{quantita_disponibile}, "
                        f"richiesta {riga.quantita_richiesta})"
                    ),
                )
            riga.item.quantita_disponibile = (
                quantita_disponibile - riga.quantita_richiesta
            )
            db.add(riga.item)
            movimento = MagazzinoMovimento(
                item_id=riga.item.id,
                tipo=MagazzinoMovimentoTipoEnum.scarico,
                quantita=riga.quantita_richiesta,
                cantiere_id=richiesta.cantiere_id,
                user_id=current_user.id,
                riferimento_richiesta_id=richiesta.id,
            )
            db.add(movimento)

        richiesta.stato = MagazzinoRichiestaStatusEnum.evasa
        richiesta.gestito_da_user_id = current_user.id
        richiesta.gestito_at = datetime.utcnow()
        richiesta.letto_da_richiedente = False
        db.add(richiesta)

        db.commit()
    except HTTPException as exc:
        db.rollback()
        return templates.TemplateResponse(
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": exc.detail,
            },
            status_code=exc.status_code,
        )
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "manager/magazzino/richiesta_detail.html",
            {
                "request": request,
                "user": current_user,
                "richiesta": richiesta,
                "error_message": "Errore durante l'evasione della richiesta.",
            },
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
    richiesta = db.query(MagazzinoRichiesta).filter(MagazzinoRichiesta.id == richiesta_id).first()
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
        )

    richiesta.stato = MagazzinoRichiestaStatusEnum.rifiutata
    richiesta.risposta_manager = (risposta_manager or "").strip() or None
    richiesta.gestito_da_user_id = current_user.id
    richiesta.gestito_at = datetime.utcnow()
    richiesta.letto_da_richiedente = False

    db.add(richiesta)
    db.commit()

    return RedirectResponse(
        url=request.url_for(
            "manager_magazzino_richiesta_detail", richiesta_id=richiesta.id
        ),
        status_code=303,
    )
