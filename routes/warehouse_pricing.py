"""Reference costs, independently from catalogue and stock editing."""
import hashlib
import hmac
import secrets
import time
from math import isfinite
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import SECRET_KEY, get_current_active_user_html
from audit_utils import log_audit_event
from database import get_db
from models import MagazzinoItem, User
from permissions import can_access_warehouse_area, can_manage_warehouse_prices
from services.warehouse_overview import valuation
from template_context import render_template, register_manager_badges

router = APIRouter(tags=['prezzi magazzino'])
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


def token(user):
    value = f'{user.id}:{int(time.time())}:{secrets.token_hex(12)}'
    return value + ':' + hmac.new(SECRET_KEY.encode(), ('warehouse-price:' + value).encode(), hashlib.sha256).hexdigest()


def validate(request, user, csrf):
    if not can_manage_warehouse_prices(user):
        raise HTTPException(403, 'Permessi insufficienti')
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, 'Origine non valida')
    try:
        uid, stamp, nonce, signature = csrf.split(':')
        value = f'{uid}:{stamp}:{nonce}'
        expected = hmac.new(SECRET_KEY.encode(), ('warehouse-price:' + value).encode(), hashlib.sha256).hexdigest()
        valid = str(user.id) == uid and 0 <= time.time() - int(stamp) <= 7200 and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, 'Ricaricare la pagina prima di riprovare')


def render_prices(request, db, user, q='', missing=False, page=1, *, error=None, edited_id=None, entered='', status=200):
    q = q.strip()[:150]
    query = db.query(MagazzinoItem).filter(MagazzinoItem.attivo.is_(True))
    if q:
        query = query.filter(or_(MagazzinoItem.nome.ilike(f'%{q}%'), MagazzinoItem.codice.ilike(f'%{q}%')))
    if missing:
        query = query.filter(MagazzinoItem.costo_unitario.is_(None))
    total = query.count()
    pages = max(1, (total + 24) // 25)
    page = max(1, min(page, pages))
    items = query.order_by(MagazzinoItem.nome, MagazzinoItem.id).offset((page-1)*25).limit(25).all()
    if edited_id and not any(item.id == edited_id for item in items):
        edited = db.query(MagazzinoItem).filter_by(id=edited_id, attivo=True).first()
        if edited:
            items.insert(0, edited)
    return render_template(templates, request, 'manager/magazzino/prices.html', dict(
        items=items, q=q, missing=missing, page=page, pages=pages, total=total, valuation=valuation(db),
        can_edit_prices=can_manage_warehouse_prices(user), csrf=token(user), error=error,
        edited_id=edited_id, entered=entered,
    ), db, user, status_code=status)


@router.get('/manager/magazzino/prezzi', name='warehouse_prices')
def prices(request: Request, q: str = '', missing: bool = False, page: int = 1,
           db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    if not can_access_warehouse_area(user):
        raise HTTPException(403, 'Permessi insufficienti')
    return render_prices(request, db, user, q, missing, page)


@router.post('/manager/magazzino/items/{item_id}/prezzo', name='warehouse_price_save')
def save_price(item_id: int, request: Request, cost: str = Form(''), expected: str = Form(''),
               csrf: str = Form(''), q: str = Form(''), missing: bool = Form(False), page: int = Form(1),
               db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user, csrf)
    item = db.query(MagazzinoItem).filter_by(id=item_id, attivo=True).populate_existing().with_for_update().first()
    if not item:
        raise HTTPException(404, 'Articolo non trovato')
    fr = request.cookies.get('lang') == 'fr'
    def invalid(it, french, status=400):
        db.rollback()
        return render_prices(request, db, user, q, missing, page, error=french if fr else it,
                             edited_id=item_id, entered=cost, status=status)
    try:
        value = float(cost.strip().replace(',', '.')) if cost.strip() else None
        if value is not None and (not isfinite(value) or value < 0 or not isfinite(value * item.quantita_disponibile)):
            raise ValueError()
    except ValueError:
        return invalid('Inserisci un costo valido, maggiore o uguale a zero. Il campo vuoto indica un prezzo non disponibile.',
                       'Saisissez un coût valide, supérieur ou égal à zéro. Un champ vide indique un prix indisponible.')
    current = '' if item.costo_unitario is None else str(item.costo_unitario)
    if expected != current:
        return invalid('Il costo è cambiato nel frattempo. Controlla il costo attuale e salva nuovamente.',
                       'Le coût a changé entre-temps. Vérifiez le coût actuel puis enregistrez à nouveau.', 409)
    previous = item.costo_unitario
    item.costo_unitario = value
    log_audit_event(db, user, 'WAREHOUSE_UNIT_COST_UPDATED', 'magazzino_item', item.id,
                   {'before': previous, 'after': value, 'unit': item.unita_misura})
    db.commit()
    return RedirectResponse(str(request.url_for('warehouse_prices').include_query_params(
        q=q.strip()[:150], missing='true' if missing else 'false', page=page, saved=item_id)), 303)
