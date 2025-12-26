from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from auth import get_current_active_user_html
from database import get_db
from models import (
    MagazzinoItem,
    MagazzinoRichiesta,
    MagazzinoRichiestaRiga,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
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


@router.get(
    "/capo/magazzino",
    response_class=HTMLResponse,
    name="capo_magazzino_list",
)
def capo_magazzino_list(
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
        "capo/magazzino/items_list.html",
        {"request": request, "user": current_user, "items": items},
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

    righe: list[tuple[int, float]] = []
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

        item = db.query(MagazzinoItem).filter(MagazzinoItem.id == parsed_item_id).first()
        if not item or not item.attivo:
            raise HTTPException(status_code=400, detail="Item non disponibile")
        righe.append((parsed_item_id, parsed_quantita))

    if not righe:
        raise HTTPException(status_code=400, detail="Nessuna riga valida")

    richiesta = MagazzinoRichiesta(
        richiesto_da_user_id=current_user.id,
        note=note.strip() or None,
    )
    db.add(richiesta)
    db.flush()

    for item_id_value, quantita_value in righe:
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    items = db.query(MagazzinoItem).order_by(MagazzinoItem.nome.asc()).all()
    return templates.TemplateResponse(
        "manager/magazzino/items_list.html",
        {"request": request, "user": current_user, "items": items},
    )


@router.get(
    "/manager/magazzino/nuovo",
    response_class=HTMLResponse,
    name="manager_magazzino_new",
)
def manager_magazzino_new(
    request: Request,
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)
    return templates.TemplateResponse(
        "manager/magazzino/item_new.html",
        {
            "request": request,
            "user": current_user,
            "item": None,
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
    unita_misura: str = Form(...),
    descrizione: str = Form(""),
    quantita_disponibile: str | None = Form(""),
    soglia_minima: str | None = Form(""),
    attivo: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user_html),
):
    ensure_magazzino_manager(current_user)

    item = MagazzinoItem(
        nome=nome.strip(),
        unita_misura=unita_misura.strip(),
        descrizione=(descrizione or "").strip() or None,
        quantita_disponibile=_parse_float(quantita_disponibile) or 0.0,
        soglia_minima=_parse_float(soglia_minima),
        attivo=attivo,
    )
    db.add(item)
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

    return templates.TemplateResponse(
        "manager/magazzino/item_edit.html",
        {
            "request": request,
            "user": current_user,
            "item": item,
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
    unita_misura: str = Form(...),
    descrizione: str = Form(""),
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

    item.nome = nome.strip()
    item.unita_misura = unita_misura.strip()
    item.descrizione = (descrizione or "").strip() or None
    item.quantita_disponibile = _parse_float(quantita_disponibile) or 0.0
    item.soglia_minima = _parse_float(soglia_minima)
    item.attivo = attivo

    db.add(item)
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
    richiesta = db.query(MagazzinoRichiesta).filter(MagazzinoRichiesta.id == richiesta_id).first()
    if not richiesta:
        return RedirectResponse(
            url=request.url_for("manager_magazzino_richieste"),
            status_code=303,
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
