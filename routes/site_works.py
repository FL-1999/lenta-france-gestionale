from datetime import datetime
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from pydantic import Field, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_active_user_html
from audit_utils import log_audit_event
from database import get_db
from models import SitePlan, SiteWorksMap, SiteStrutDrawing, User
from permissions import has_perm
from routes.site_plans import access, same_origin, templates, elements
from services.plan_selection import current_plan
from services.site_plan_import import MAX_PDF_BYTES
from services.site_works import Strict, Works, Strut, Key, empty_works, validate_works, object_ids, merge_import, counts
from services.strut_drawing import read_pdf
from template_context import render_template

router=APIRouter(prefix='/manager/cantieri/{site_id}/avanzamento',tags=['mappa lavori'])


def approved_reference(db,site_id):
    plan=current_plan(db.query(SitePlan).filter(SitePlan.site_id==site_id,SitePlan.approved.isnot(None),SitePlan.removed_at.is_(None)).all())
    return dict(plan_id=plan.id,revision=plan.approved_revision,filename=plan.filename,layout=json.loads(plan.approved)) if plan else None


def snapshot(db,site):
    row=db.get(SiteWorksMap,site.id)
    if row:
        return row.revision,json.loads(row.payload),json.loads(row.reference)
    return 0,empty_works(site),approved_reference(db,site.id)


def source(db,site_id,source_id):
    row=db.query(SiteStrutDrawing).filter_by(site_id=site_id,id=source_id).first()
    if not row:
        raise HTTPException(404,'PDF non trovato in questo cantiere.')
    return row


def persist(db,site,user,revision,value,reference,removed=None,action='WORKS_MAP_UPDATED'):
    if not reference:
        raise HTTPException(400,'Convalida prima una pianta delle paratie.')
    old_revision,old,old_reference=snapshot(db,site)
    if revision!=old_revision:
        raise HTTPException(409,'La mappa è cambiata in un’altra sessione. Ricarica prima di salvare.')
    if not old_reference:
        raise HTTPException(409,'La pianta convalidata non è più disponibile. Ricarica la mappa.')
    # On first save the caller must still be looking at the same approved plan.
    if old_reference['plan_id']!=reference['plan_id'] or old_reference['revision']!=reference['revision']:
        raise HTTPException(409,'La pianta di riferimento è cambiata. Ricarica la mappa.')
    reference=old_reference
    try:
        value=validate_works(value,old_reference['layout'])
        lost=object_ids(old)-object_ids(value)
        if lost-set(removed or []):
            raise ValueError('Conferma esplicitamente l’eliminazione degli elementi rimossi.')
        for level in value['levels']:
            for s in level['struts']:
                if s['source_id'] is not None:
                    source(db,site.id,s['source_id'])
    except (ValueError,ValidationError) as exc:
        raise HTTPException(400,str(exc)) from exc
    payload=json.dumps(value,ensure_ascii=False)
    try:
        if old_revision:
            changed=db.query(SiteWorksMap).filter_by(site_id=site.id,revision=revision).update(
                dict(payload=payload,revision=revision+1,updated_at=datetime.utcnow()),synchronize_session=False)
            if changed!=1:
                db.rollback()
                raise HTTPException(409,'La mappa è stata aggiornata. Ricarica prima di salvare.')
        else:
            db.add(SiteWorksMap(site_id=site.id,revision=1,payload=payload,reference=json.dumps(reference)))
            db.flush()
        log_audit_event(db,user,action,'site',site.id,{'revision':revision+1,'removed':sorted(lost),**counts(value)})
        db.commit();db.expire_all()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409,'Un’altra sessione ha creato la mappa. Ricarica.') from exc
    return {'revision':revision+1,'works':value}


class Save(Strict):
    revision:int=Field(ge=0)
    plan_id:int=Field(gt=0)
    plan_revision:int=Field(ge=1)
    works:Works
    confirm_remove:list[Key]=Field(default_factory=list,max_length=10000)


class Import(Save):
    level_id:Key
    source_id:int=Field(gt=0)
    struts:list[Strut]=Field(max_length=300,min_length=1)
    reviewed:bool=False


@router.get('')
def page(request:Request,site_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id)
    return render_template(templates,request,'manager/site_works.html',
        {'site':site,'can_edit':has_perm(user,'sites.update')},db=db,user=user)


@router.get('/data')
def data(site_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id)
    revision,value,reference=snapshot(db,site)
    current=approved_reference(db,site_id)
    from main import _build_site_progress
    summary,_,_=_build_site_progress(site,'it')
    return dict(revision=revision,works=value,reference=reference,
        reference_changed=bool(reference and (not current or (current['plan_id'],current['revision'])!=(reference['plan_id'],reference['revision']))),
        can_edit=has_perm(user,'sites.update'),elements=elements(db,site,user),summary=summary,
        legacy_levels=[dict(name=f'Livello -{l.level_index}',quota=l.level_quota,total=l.total_struts_level,done=l.done_struts_level) for l in site.strut_levels],
        sources=[dict(id=s.id,filename=s.filename,page=s.page_number) for s in db.query(SiteStrutDrawing).filter_by(site_id=site_id).order_by(SiteStrutDrawing.id.desc()).all()])


@router.put('/data')
def save(request:Request,site_id:int,body:Save,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    return persist(db,site,user,body.revision,body.works.model_dump(mode='json'),
        dict(plan_id=body.plan_id,revision=body.plan_revision),body.confirm_remove)


@router.post('/conferma-lettura')
def confirm_read(request:Request,site_id:int,body:Import,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request);source(db,site_id,body.source_id)
    if not body.reviewed:
        raise HTTPException(400,'Controlla dati e appoggi prima di confermare.')
    _,existing,_=snapshot(db,site)
    try:
        value=merge_import(existing,body.level_id,[s.model_dump(mode='json') for s in body.struts],body.source_id)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return persist(db,site,user,body.revision,value,dict(plan_id=body.plan_id,revision=body.plan_revision),action='STRUT_DRAWING_CONFIRMED')


@router.post('/leggi-pdf')
async def upload(request:Request,site_id:int,file:UploadFile=File(...),page_number:int=Form(1),db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id,True);same_origin(request)
    contents=await file.read(MAX_PDF_BYTES+1)
    try:
        proposal,preview=await run_in_threadpool(read_pdf,contents,page_number)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    row=SiteStrutDrawing(site_id=site_id,filename=(file.filename or 'puntoni.pdf')[:300],page_number=page_number,
        pdf_data=contents,preview_data=preview,proposal=json.dumps(proposal))
    db.add(row);db.flush()
    log_audit_event(db,user,'STRUT_DRAWING_READ','site',site_id,{'source_id':row.id,'page':page_number})
    db.commit()
    return {'id':row.id,**proposal}


class Crop(Strict):
    crop:list[float] | None=None


@router.post('/pdf/{source_id}/rileggi')
def reread(request:Request,site_id:int,source_id:int,body:Crop,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id,True);same_origin(request);row=source(db,site_id,source_id)
    try:
        proposal,_=read_pdf(row.pdf_data,row.page_number,body.crop)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'id':row.id,**proposal}


@router.get('/pdf/{source_id}/{kind}')
def drawing(site_id:int,source_id:int,kind:str,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id);row=source(db,site_id,source_id)
    if kind not in ('originale','anteprima'):
        raise HTTPException(404)
    return Response(row.pdf_data if kind=='originale' else row.preview_data,
        media_type='application/pdf' if kind=='originale' else 'image/png',
        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
                 'Content-Disposition':"inline; filename*=UTF-8''"+quote(row.filename if kind=='originale' else 'anteprima.png',safe='')})
