from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from auth import get_current_active_user_html
from database import get_db
from models import ProjectPartner, ProjectPartnerSite, Site
from routes.site_costs import token, validate, access
from services import project_directory as svc
from template_context import render_template, register_manager_badges

router = APIRouter(prefix='/manager/rubrica', tags=['project-directory'])
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


def render(request, db, user, template, **context):
    access(user)
    return render_template(templates, request, 'manager/directory/'+template+'.html',
                           dict(categories=svc.CATEGORIES, csrf=token(user), **context), db, user)


@router.get('')
def index(request: Request, q: str = '', category: str = '', archived: bool = False, page: int = 1,
          db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user)
    rows = db.query(ProjectPartner).options(selectinload(ProjectPartner.projects)).filter_by(active=not archived).order_by(ProjectPartner.name).all()
    q = q.strip()[:255]
    rows = [r for r in rows if (not category or category in r.payload['categories']) and
            (not q or q.casefold() in ' '.join(str(r.payload.get(k, '')) for k in ('name', 'contact_name', 'city', 'email')).casefold())]
    count = len(rows); page = max(1, min(page, max(1, (count+29)//30)))
    return render(request, db, user, 'index', rows=rows[(page-1)*30:page*30], total=count,
                  q=q, category=category, archived=archived, page=page)


def form(request, db, user, row=None):
    sites = [dict(id=s.id, **svc.site_snapshot(s)) for s in db.query(Site).order_by(Site.name)]
    return render(request, db, user, 'form', record=svc.serialize(row) if row else None, sites=sites)


@router.get('/nuovo')
def new(request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user); return form(request, db, user)


@router.get('/{partner_id}/modifica')
def edit(partner_id: int, request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user); return form(request, db, user, svc.partner_row(db, partner_id))


@router.get('/{partner_id}')
def detail(partner_id: int, request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user); return render(request, db, user, 'detail', record=svc.serialize(svc.partner_row(db, partner_id)))


@router.post('')
async def save(request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    validate(request, user)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Dati non validi / Données invalides')
    try:
        row = svc.save(db, body, user)
        db.commit()
        return dict(id=row.id, revision=row.revision)
    except HTTPException:
        db.rollback(); raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Scheda già presente o collegamento modificato. Ricarica. / Fiche existante ou association modifiée. Actualisez.')
