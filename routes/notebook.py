import hashlib
import hmac
import secrets
import time
import logging
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.templating import Jinja2Templates
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from auth import SECRET_KEY, get_current_active_user_html
from database import get_db
from models import NotebookNote, NotebookRevision, User
from template_context import register_manager_badges, render_template
from services import notebook as svc, notebook_ai as ai

class PrivateNoteRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except SQLAlchemyError as exc:
                # SQLAlchemy exception strings may contain bound private note contents.
                logging.getLogger(__name__).warning('Notebook storage failure: %s', type(exc).__name__)
                raise HTTPException(503, 'Salvataggio non completato: ricarica per verificare e riprova / Enregistrement non terminé : rechargez et réessayez') from None
        return private_handler


router = APIRouter(prefix='/appunti', tags=['Appunti personali'], route_class=PrivateNoteRoute)
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


def token(user):
    value = f'{user.id}:{int(time.time())}:{secrets.token_hex(12)}'
    return value + ':' + hmac.new(SECRET_KEY.encode(), ('notebook:' + value).encode(), hashlib.sha256).hexdigest()


def validate(request, user):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, 'Origine non autorizzata / Origine non autorisée')
    try:
        uid, stamp, nonce, signature = request.headers.get('x-csrf-token', '').split(':')
        expected = hmac.new(SECRET_KEY.encode(), f'notebook:{uid}:{stamp}:{nonce}'.encode(), hashlib.sha256).hexdigest()
        valid = uid == str(user.id) and 0 <= time.time() - int(stamp) <= 7200 and hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(403, 'Ricarica la pagina prima di salvare / Rechargez la page avant d’enregistrer')


@router.get('', name='notebook_workspace')
def page(request: Request, cantiere: int | None = None, db: Session = Depends(get_db),
         user: User = Depends(get_current_active_user_html)):
    site = next((s for s in svc.sites(db, user) if s.id == cantiere), None) if cantiere else None
    if cantiere and site is None:
        raise HTTPException(404, 'Quaderno non trovato / Carnet introuvable')
    return render_template(templates, request, 'notebook/workspace.html',
        {'notebook_csrf': token(user), 'notebook_site': site}, db, user)


@router.get('/data')
def listing(scope: str = Query('mine', pattern='^(mine|received|archived|all)$'), site_id: int | None = None,
            collection: str = Query('', max_length=100), q: str = Query('', max_length=200),
            offset: int = Query(0, ge=0), db: Session = Depends(get_db),
            user: User = Depends(get_current_active_user_html)):
    query = svc.visible_query(db, user)
    if scope == 'mine':
        query = query.filter(NotebookNote.owner_id == user.id, NotebookNote.archived.is_(False))
    elif scope == 'received':
        query = query.filter(NotebookNote.owner_id != user.id, NotebookNote.archived.is_(False))
    else:
        query = query.filter(NotebookNote.archived.is_(scope == 'archived'))
    if site_id:
        query = query.filter(NotebookNote.site_id == site_id)
    if collection:
        query = query.filter(NotebookNote.owner_id == user.id, NotebookNote.collection == collection)
    if q.strip():
        query = query.filter(NotebookNote.title.icontains(q.strip(), autoescape=True))
    rows = query.order_by(NotebookNote.updated_at.desc(), NotebookNote.id.desc()).offset(offset).limit(51).all()
    collections = [s[0] for s in db.query(NotebookNote.collection).filter_by(owner_id=user.id).filter(
        NotebookNote.collection != '').distinct().order_by(NotebookNote.collection)]
    return {'notes': [svc.data(db, row, user) for row in rows[:50]], 'more': len(rows) > 50,
        'collections': collections, 'sites': [{'id': s.id, 'name': s.name} for s in svc.sites(db, user)],
        'assignable_sites': [{'id': s.id, 'name': s.name, 'code': s.code or ''} for s in svc.assignable_sites(db, user)],
        'ai_enabled': ai.configuration(user)[0]}


@router.post('')
def create(request: Request, body: svc.Create, db: Session = Depends(get_db),
           user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    try:
        row = svc.create(db, user, body)
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(NotebookNote).filter_by(owner_id=user.id, request_key=body.request_key).first()
        if row is None:
            raise HTTPException(409, 'Ricarica e riprova / Rechargez et réessayez') from None
    return svc.data(db, row, user, full=True)


@router.get('/{ident:int}')
def read(ident: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    return svc.data(db, svc.find(db, ident, user), user, full=True)


@router.put('/{ident:int}')
def edit(ident: int, body: svc.Edit, request: Request, db: Session = Depends(get_db),
         user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    row = svc.find(db, ident, user, edit=True)
    svc.edit(db, row, user, body)
    db.commit()
    return svc.data(db, row, user, full=True)


@router.get('/{ident:int}/destinatari')
def recipients(ident: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    svc.find(db, ident, user, owner=True)
    return [{'id': u.id, 'name': u.full_name or u.email} for u in db.query(User).filter(
        User.id != user.id, User.is_active.is_(True)).order_by(User.full_name, User.id)]


@router.put('/{ident:int}/condivisione')
def share(ident: int, body: svc.Sharing, request: Request, db: Session = Depends(get_db),
          user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    row = svc.find(db, ident, user, owner=True)
    svc.share(db, row, user, body)
    db.commit()
    return svc.data(db, row, user, full=True)


@router.put('/{ident:int}/archivio')
def archive(ident: int, body: svc.Archive, request: Request, db: Session = Depends(get_db),
            user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    row = svc.find(db, ident, user, owner=True)
    svc.version_write(db, row, body.version, user, {'archived': body.archived})
    db.commit()
    return svc.data(db, row, user, full=True)


@router.get('/{ident:int}/originali')
def originals(ident: int, offset: int = Query(0, ge=0), db: Session = Depends(get_db),
              user: User = Depends(get_current_active_user_html)):
    svc.find(db, ident, user, owner=True)
    rows = db.query(NotebookRevision).filter_by(note_id=ident).order_by(NotebookRevision.id.desc()).offset(offset).limit(21).all()
    return {'revisions': [dict(version=r.version, content=r.content, created_at=r.created_at) for r in rows[:20]],
            'more': len(rows) > 20}


@router.post('/{ident:int}/riordina')
def prepare(ident: int, body: ai.Prepare, request: Request, db: Session = Depends(get_db),
            user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    row = svc.find(db, ident, user, owner=True)
    draft = ai.prepare(db, user, row, body)
    return {'id': draft.id, 'result': draft.result, 'mode': draft.mode}


@router.post('/{ident:int}/bozze/{draft_id}/crea-appunti')
def extract(ident: int, draft_id: str, body: ai.SplitAccept, request: Request,
            db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    row = svc.find(db, ident, user, owner=True)
    ai.extract(db, user, row, draft_id, body)
    db.commit()
    return svc.data(db, row, user, full=True)


@router.post('/{ident:int}/bozze/{draft_id}/{decision}')
def decide(ident: int, draft_id: str, decision: str, body: svc.Version, request: Request,
           db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    validate(request, user)
    if decision not in ('accetta', 'scarta'):
        raise HTTPException(404)
    row = svc.find(db, ident, user, owner=True)
    ai.decide(db, user, row, draft_id, body, decision == 'accetta')
    db.commit()
    return svc.data(db, row, user, full=True)
