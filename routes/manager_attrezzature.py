"""Gestione anagrafica Attrezzature (CRUD) lato manager.

Fase 2: schermata per creare / modificare / eliminare le attrezzature con
nome libero e categoria (nomenclatura). Il codice e il QR vengono generati
automaticamente in base alla categoria (es. POMPA-001, PERFOR-002).
"""

import io
import logging
import re
import time

import segno
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from database import get_db
from models import Attrezzatura, AttrezzaturaStatoEnum, User
from permissions import has_perm
from template_context import register_manager_badges, render_template

templates = Jinja2Templates(directory="templates")
register_manager_badges(templates)
router = APIRouter(tags=["manager-attrezzature"])

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100
STATI_VALIDI = [s.value for s in AttrezzaturaStatoEnum]

perf_logger = logging.getLogger("lenta_france_gestionale.performance")


def _ensure_manager(user: User) -> None:
    if not has_perm(user, "manager.access"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")


def _normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    page = max(1, page)
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return page, per_page


def _category_prefix(tipo: str | None) -> str:
    """Ricava un prefisso codice dalla categoria (solo lettere/numeri, maiuscolo)."""
    base = re.sub(r"[^A-Za-z0-9]", "", (tipo or "")).upper()
    return (base[:6] or "ATT")


def _next_codice(db: Session, prefix: str) -> str:
    """Prossimo progressivo libero per il prefisso dato (es. POMPA-001)."""
    rows = db.query(Attrezzatura.codice).filter(Attrezzatura.codice.like(f"{prefix}-%")).all()
    max_n = 0
    for (codice,) in rows:
        suffix = (codice or "").rsplit("-", 1)[-1]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    n = max_n + 1
    # Salvaguardia contro collisioni residue su codice/qr_code.
    while True:
        candidate = f"{prefix}-{n:03d}"
        exists = (
            db.query(Attrezzatura.id)
            .filter((Attrezzatura.codice == candidate) | (Attrezzatura.qr_code == candidate))
            .first()
        )
        if not exists:
            return candidate
        n += 1


def _qr_svg(data: str) -> str:
    """SVG del QR (senza intestazione XML, dimensionato via CSS)."""
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=2, svgclass=None, xmldecl=False, omitsize=True)
    return buf.getvalue().decode("utf-8")


def _label_items(attrezzature: list[Attrezzatura]) -> list[dict]:
    """Prepara i dati (con QR SVG) per il template etichette."""
    return [
        {"codice": a.codice, "nome": a.nome, "tipo": a.tipo, "qr": _qr_svg(a.qr_code or a.codice)}
        for a in attrezzature
    ]


def _distinct_categorie(db: Session) -> list[str]:
    rows = (
        db.query(Attrezzatura.tipo)
        .filter(Attrezzatura.tipo.isnot(None))
        .distinct()
        .order_by(Attrezzatura.tipo.asc())
        .all()
    )
    return [r[0] for r in rows if (r[0] or "").strip()]


@router.get("/manager/attrezzature", response_class=HTMLResponse, name="manager_attrezzature_list")
def manager_attrezzature_list(
    request: Request,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    categoria: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    page, per_page = _normalize_pagination(page, per_page)

    query = db.query(Attrezzatura)
    if categoria and categoria.strip():
        query = query.filter(func.lower(Attrezzatura.tipo) == categoria.strip().lower())
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (Attrezzatura.nome.ilike(like))
            | (Attrezzatura.codice.ilike(like))
            | (Attrezzatura.qr_code.ilike(like))
        )

    total_count = query.with_entities(func.count(Attrezzatura.id)).scalar() or 0
    started = time.monotonic()
    attrezzature = (
        query.order_by(Attrezzatura.tipo.asc(), Attrezzatura.codice.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    perf_logger.debug(
        "manager_attrezzature_list rows=%s total=%s duration_ms=%.2f",
        len(attrezzature),
        total_count,
        (time.monotonic() - started) * 1000,
    )

    return render_template(
        templates,
        request,
        "manager/attrezzature/list.html",
        {
            "attrezzature": attrezzature,
            "categorie": _distinct_categorie(db),
            "stati": STATI_VALIDI,
            "filtro_categoria": categoria or "",
            "filtro_q": q or "",
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": max(1, (total_count + per_page - 1) // per_page),
        },
        db,
        current_user,
    )


@router.get("/manager/attrezzature/nuova", response_class=HTMLResponse, name="manager_attrezzature_new")
def manager_attrezzature_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    return render_template(
        templates,
        request,
        "manager/attrezzature/new.html",
        {
            "categorie": _distinct_categorie(db),
            "stati": STATI_VALIDI,
        },
        db,
        current_user,
    )


@router.post("/manager/attrezzature/nuova", response_class=HTMLResponse, name="manager_attrezzature_create")
def manager_attrezzature_create(
    request: Request,
    nome: str = Form(...),
    categoria: str = Form(...),
    stato: str = Form("disponibile"),
    posizione_attuale: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)

    tipo = (categoria or "").strip()
    nome_clean = (nome or "").strip()
    if not tipo or not nome_clean:
        raise HTTPException(status_code=400, detail="Nome e categoria sono obbligatori")

    try:
        stato_enum = AttrezzaturaStatoEnum(stato)
    except ValueError:
        stato_enum = AttrezzaturaStatoEnum.disponibile

    codice = _next_codice(db, _category_prefix(tipo))
    attrezzatura = Attrezzatura(
        codice=codice,
        qr_code=codice,  # il QR codifica direttamente il codice
        nome=nome_clean,
        tipo=tipo,
        stato=stato_enum,
        posizione_attuale=(posizione_attuale or "").strip() or None,
    )
    db.add(attrezzatura)
    db.commit()

    return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)


@router.get("/manager/attrezzature/{attrezzatura_id}/modifica", response_class=HTMLResponse, name="manager_attrezzature_edit")
def manager_attrezzature_edit(
    attrezzatura_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.id == attrezzatura_id).first()
    if not attrezzatura:
        return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)
    return render_template(
        templates,
        request,
        "manager/attrezzature/edit.html",
        {
            "attrezzatura": attrezzatura,
            "categorie": _distinct_categorie(db),
            "stati": STATI_VALIDI,
        },
        db,
        current_user,
    )


@router.post("/manager/attrezzature/{attrezzatura_id}/modifica", response_class=HTMLResponse, name="manager_attrezzature_update")
def manager_attrezzature_update(
    attrezzatura_id: int,
    request: Request,
    nome: str = Form(...),
    categoria: str = Form(...),
    stato: str = Form("disponibile"),
    posizione_attuale: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.id == attrezzatura_id).first()
    if not attrezzatura:
        return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)

    nome_clean = (nome or "").strip()
    tipo = (categoria or "").strip()
    if not nome_clean or not tipo:
        raise HTTPException(status_code=400, detail="Nome e categoria sono obbligatori")

    try:
        stato_enum = AttrezzaturaStatoEnum(stato)
    except ValueError:
        stato_enum = attrezzatura.stato

    # Codice e QR restano stabili: non si rinumerano al cambio categoria.
    attrezzatura.nome = nome_clean
    attrezzatura.tipo = tipo
    attrezzatura.stato = stato_enum
    attrezzatura.posizione_attuale = (posizione_attuale or "").strip() or None
    db.add(attrezzatura)
    db.commit()

    return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)


@router.get("/manager/attrezzature/etichette", response_class=HTMLResponse, name="manager_attrezzature_labels")
def manager_attrezzature_labels(
    request: Request,
    categoria: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    """Pagina stampabile con le etichette QR di tutte le attrezzature (rispetta i filtri)."""
    _ensure_manager(current_user)
    query = db.query(Attrezzatura)
    if categoria and categoria.strip():
        query = query.filter(func.lower(Attrezzatura.tipo) == categoria.strip().lower())
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (Attrezzatura.nome.ilike(like))
            | (Attrezzatura.codice.ilike(like))
            | (Attrezzatura.qr_code.ilike(like))
        )
    attrezzature = query.order_by(Attrezzatura.tipo.asc(), Attrezzatura.codice.asc()).all()
    return render_template(
        templates,
        request,
        "manager/attrezzature/labels.html",
        {"items": _label_items(attrezzature), "single": False},
        db,
        current_user,
    )


@router.get("/manager/attrezzature/{attrezzatura_id}/etichetta", response_class=HTMLResponse, name="manager_attrezzature_label")
def manager_attrezzature_label(
    attrezzatura_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    """Pagina stampabile con l'etichetta QR di una singola attrezzatura."""
    _ensure_manager(current_user)
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.id == attrezzatura_id).first()
    if not attrezzatura:
        return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)
    return render_template(
        templates,
        request,
        "manager/attrezzature/labels.html",
        {"items": _label_items([attrezzatura]), "single": True},
        db,
        current_user,
    )


@router.post("/manager/attrezzature/{attrezzatura_id}/elimina", response_class=HTMLResponse, name="manager_attrezzature_delete")
def manager_attrezzature_delete(
    attrezzatura_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    _ensure_manager(current_user)
    if not has_perm(current_user, "records.delete"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    attrezzatura = db.query(Attrezzatura).filter(Attrezzatura.id == attrezzatura_id).first()
    if attrezzatura:
        db.delete(attrezzatura)
        db.commit()
    return RedirectResponse(url=request.url_for("manager_attrezzature_list"), status_code=303)
