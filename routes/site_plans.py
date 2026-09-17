from datetime import datetime
import json
import math
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, FiniteFloat
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from audit_utils import log_audit_event
from database import get_db
from deps import get_site_for_user
from models import (SitePlan, SiteProgressGridName, SiteCoupeAssignment,
                    SiteSpecialEquipmentConfig, Fiche, RoleEnum, User)
from permissions import has_perm
from services.site_plan_project import confirm_project_panels
from services.site_plan_import import import_pdf, MAX_PDF_BYTES, MAX_PANELS, layout_scale, needs_extent_review
from template_context import register_manager_badges, render_template

router=APIRouter(prefix='/manager/cantieri/{site_id}/pianta', tags=['pianta cantiere'])
templates=Jinja2Templates(directory='templates')
register_manager_badges(templates)


def access(db, user, site_id, edit=False):
    if not (has_perm(user,'manager.access') or user.role==RoleEnum.caposquadra):
        raise HTTPException(403,'Permessi insufficienti')
    if edit and not has_perm(user,'sites.update'):
        raise HTTPException(403,'Solo i responsabili possono modificare la pianta')
    return get_site_for_user(db,site_id,user)


def same_origin(request):
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.url.netloc:
        raise HTTPException(403,'Origine della richiesta non valida')


def find_plan(db, site_id, plan_id):
    row=db.query(SitePlan).filter_by(site_id=site_id,id=plan_id).first()
    if not row: raise HTTPException(404,'Pianta non trovata')
    return row


def elements(db, site, user):
    total=next((getattr(site,k) for k in ['numero_totale_paratie','totale_paratie_da_scavare','paratie_total_panels']
                if getattr(site,k) is not None),0)
    labels={r.numero_elemento:r.nome_personalizzato for r in db.query(SiteProgressGridName).filter_by(site_id=site.id,tipologia_scavo='paratia')}
    fiches={r.numero_pannello:r for r in db.query(Fiche).filter_by(site_id=site.id,tipologia_scavo='paratia')}
    assignments={r.numero_elemento:r.coupe for r in db.query(SiteCoupeAssignment).filter_by(site_id=site.id,tipologia_scavo='paratia')}
    equipment={r.numero_elemento:r for r in db.query(SiteSpecialEquipmentConfig).filter_by(site_id=site.id,tipologia_scavo='paratia')}
    numbers=set(range(1,min(int(total or 0),5000)+1))|set(fiches)|set(assignments)
    result=[]
    for n in sorted(numbers):
        f,c,e=fiches.get(n),assignments.get(n),equipment.get(n)
        result.append({'number':n,'label':labels.get(n,str(n)), 'custom_label':labels.get(n),
            'fiche_id':f.id if f else None,
            'create_url':(f'/manager/fiches/nuova?cantiere_id={site.id}&numero_pannello={n}&tipologia_scavo=paratia' if has_perm(user,'manager.access') else f'/capo/fiches/nuova?cantiere_id={site.id}&numero_pannello={n}&tipologia_scavo=paratia') if not f else None,
            'fiche_url':f'/manager/fiches/{f.id}' if f and has_perm(user,'manager.access') else None,
            'status':'cast' if f and f.data_getto and f.metri_cubi_gettati is not None else 'fiche' if f else 'planned',
            'concrete_m3':f.metri_cubi_gettati if f else None,
            'cast_date':f.data_getto.isoformat() if f and f.data_getto else None,
            'depth_m':f.profondita_totale if f else None,
            'coupe':c.nome if c else None,'armatura':c.armatura if c else None,'planned_depth_m':c.profondita_teorica if c else None,
            'sonic':bool(e.sonic_previsto) if e else bool(f and f.sonic_previsto),
            'inclinometer':bool(e.inclinometre_previsto) if e else bool(f and f.inclinometre_previsto)})
    return result


@router.get('',name='manager_site_plan')
def page(site_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id)
    return render_template(templates,request,'manager/site_plan.html',{'site':site,
        'plan_can_edit':has_perm(user,'sites.update')},db,user)


@router.get('/data')
def get_data(site_id:int,plan_id:int|None=None,draft:bool=False,
             db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id)
    editor=has_perm(user,'sites.update')
    query=db.query(SitePlan).filter_by(site_id=site_id)
    if not editor: query=query.filter(SitePlan.approved.isnot(None))
    rows=query.order_by(SitePlan.id.desc()).all()
    # Ordinary readers keep seeing the last confirmed drawing during revisions.
    row=next((r for r in rows if r.id==plan_id),None) if plan_id else max(
        (r for r in rows if r.approved),key=lambda r:r.approved_at or datetime.min,default=rows[0] if rows else None)
    if plan_id and row is None: raise HTTPException(404,'Pianta non trovata')
    plan=None
    if row:
        use_draft=editor and (draft or not row.approved)
        plan={'id':row.id,'filename':row.filename,'page_number':row.page_number,
            'revision':row.revision,'approved_revision':row.approved_revision,'editing':use_draft,
            'approved_at':row.approved_at.isoformat() if row.approved_at else None,
            'layout':json.loads(row.draft if use_draft else row.approved),
            'original_url':f'/manager/cantieri/{site_id}/pianta/{row.id}/originale',
            'preview_url':f'/manager/cantieri/{site_id}/pianta/{row.id}/anteprima'}
    return {'plan':plan,'elements':elements(db,site,user),'can_edit':editor,
        'versions':[{'id':r.id,'filename':r.filename,'approved':bool(r.approved),
                     'has_draft':r.revision!=r.approved_revision} for r in rows]}


@router.post('/importa')
def upload(site_id:int,request:Request,file:UploadFile=File(...),page_number:int=Form(1),
           db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    data=file.file.read(MAX_PDF_BYTES+1)
    try: layout,preview=import_pdf(data,page_number)
    except ValueError as e: raise HTTPException(400,str(e)) from e
    # Match only unambiguous existing names, never guess from PDF reading order.
    choices=elements(db,site,user)
    for p in layout['panels']:
        matches=[e for e in choices if e['custom_label'] and e['label'].casefold()==p['label'].casefold()]
        unique=sum(q['label'].casefold()==p['label'].casefold() for q in layout['panels'])==1
        if len(matches)==1 and unique: p['element']=matches[0]['number']
    row=SitePlan(site_id=site_id,filename=(file.filename or 'pianta.pdf')[:300],pdf_data=data,
                 preview_data=preview,page_number=page_number,draft=json.dumps(layout),updated_by_id=user.id)
    db.add(row);db.flush()
    log_audit_event(db,user,'SITE_PLAN_IMPORTED','site_plan',row.id,{'site_id':site_id,'panels':len(layout['panels'])})
    db.commit()
    return {'id':row.id,'revision':row.revision}


class PanelInput(BaseModel):
    key:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    label:str=Field(min_length=1,max_length=80)
    points:list[tuple[FiniteFloat,FiniteFloat]]=Field(min_length=4,max_length=4)
    width_m:FiniteFloat|None=Field(default=None,gt=0,le=100)
    element:int|None=Field(default=None,gt=0)
    reviewed:bool=False
    extent_confirmed:bool=False


class LayoutInput(BaseModel):
    revision:int=Field(ge=1)
    panels:list[PanelInput]=Field(max_length=MAX_PANELS)
    confirm:bool=False
    scale_ppm:FiniteFloat|None=Field(default=None,gt=0,le=10000)


def validate_layout(body,source,allowed,approve):
    if approve and (not body.confirm or not body.panels):
        raise HTTPException(400,'Controlla la pianta e conferma la convalida.')
    scale=body.scale_ppm or layout_scale(source)
    if approve and not scale: raise HTTPException(400,'Calibra la scala usando un pannello di larghezza nota.')
    keys=set();links=set();panels=[]
    original={p['key']:p for p in source['panels']}
    for p in body.panels:
        if p.key in keys: raise HTTPException(400,'Identificativo pannello ripetuto')
        keys.add(p.key)
        if not p.label.strip(): raise HTTPException(400,'Inserisci una sigla per ogni pannello')
        if p.element is not None:
            if p.element not in allowed: raise HTTPException(400,'Elemento non presente nel cantiere')
            if p.element in links: raise HTTPException(400,'Due zone non possono collegarsi allo stesso elemento')
            links.add(p.element)
        if any(not -source['width']<=x<=2*source['width'] or not -source['height']<=y<=2*source['height'] for x,y in p.points):
            raise HTTPException(400,'La sagoma supera lo spazio di lavoro disponibile')
        # Require a non-degenerate convex quadrilateral (no crossed corners).
        cross=[]
        for i in range(4):
            a,b,c=p.points[i],p.points[(i+1)%4],p.points[(i+2)%4]
            cross.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        if not (all(v>.1 for v in cross) or all(v<-.1 for v in cross)):
            raise HTTPException(400,'Sagoma non valida: controlla gli angoli del pannello')
        if approve and (p.width_m is None or not p.reviewed):
            raise HTTPException(400,f'Verifica sagoma e larghezza di {p.label}.')
        reference=original.get(p.key,{}).get('reference_points') or original.get(p.key,{}).get('points')
        extent=needs_extent_review(p.points,reference,source['width'],source['height'])
        if approve and any(abs(math.dist(p.points[i],p.points[j])/(p.width_m*scale)-1)>.02 for i,j in ((0,1),(3,2))):
            raise HTTPException(400,f'{p.label}: sagoma fuori scala. Applica la larghezza alla scala comune.')
        if approve and extent and not p.extent_confirmed:
            raise HTTPException(400,f'{p.label}: possibile sbordo. Controlla e conferma gli estremi sul PDF.')
        panel=p.model_dump();panel['label']=p.label.strip()
        panel['reference_points']=reference or p.points
        panel['recognition']=original.get(p.key,{}).get('recognition','manual')
        panel['warnings']=original.get(p.key,{}).get('warnings',[])
        panels.append(panel)
    return {**source,'panels':panels,'scale_ppm':scale}


@router.put('/{plan_id}/bozza')
@router.put('/{plan_id}/convalida')
def save(site_id:int,plan_id:int,request:Request,body:LayoutInput,
         db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    row=find_plan(db,site_id,plan_id)
    approve=request.url.path.endswith('/convalida')
    layout=validate_layout(body,json.loads(row.draft),{e['number'] for e in elements(db,site,user)},approve)
    if row.revision!=body.revision: raise HTTPException(409,'La pianta è cambiata. Ricarica prima di salvare.')
    if approve:
        confirm_project_panels(db,site,layout,json.loads(row.approved) if row.approved else None)
    new_revision=row.revision+1
    values={'draft':json.dumps(layout),'revision':new_revision,'updated_by_id':user.id}
    if approve: values.update(approved=json.dumps(layout),approved_revision=new_revision,approved_at=datetime.utcnow())
    changed=db.query(SitePlan).filter_by(id=plan_id,site_id=site_id,revision=body.revision).update(values,synchronize_session=False)
    if changed!=1:
        db.rollback();raise HTTPException(409,'La pianta è stata modificata da un altro utente.')
    log_audit_event(db,user,'SITE_PLAN_APPROVED' if approve else 'SITE_PLAN_DRAFT_SAVED','site_plan',plan_id,
                   {'site_id':site_id,'revision':new_revision,'panels':len(layout['panels'])})
    db.commit()
    return {'revision':new_revision,'approved':approve}


@router.get('/{plan_id}/originale')
@router.get('/{plan_id}/anteprima')
def original(site_id:int,plan_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id)
    row=find_plan(db,site_id,plan_id)
    if not has_perm(user,'sites.update') and not row.approved:
        raise HTTPException(404,'Pianta non convalidata')
    preview=request.url.path.endswith('/anteprima')
    return Response(row.preview_data if preview else row.pdf_data,
        media_type='image/png' if preview else 'application/pdf',
        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                 'Content-Disposition':'inline; filename="pianta.png"' if preview else 'inline; filename="pianta-originale.pdf"'})
