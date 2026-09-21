from datetime import date
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, FiniteFloat
from sqlalchemy.orm import Session
from database import get_db
from auth import get_current_active_user_html
from audit_utils import log_audit_event
from models import Site, SitePour, SiteStatusEnum, User
from routes.site_plans import access, same_origin
from services.site_pours import create_group, describe, record_joint
from permissions import has_perm

router = APIRouter(prefix='/manager/cantieri/{site_id}', tags=['cantiere e getti'])


@router.post('/stato', name='site_workspace_status')
def set_status(site_id:int, request:Request, stato:str=Form(...), conferma:bool=Form(False),
               db:Session=Depends(get_db), user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    if not conferma or stato not in ('aperto','chiuso'):
        raise HTTPException(400,'Conferma il cambio di stato del cantiere.')
    old=site.status.value if site.status else None
    site.status=SiteStatusEnum(stato)
    site.is_active=stato=='aperto'
    if stato=='chiuso' and not site.end_date: site.end_date=date.today()
    if stato=='aperto': site.end_date=None
    log_audit_event(db,user,'SITE_STATUS_CHANGED','site',site_id,{'from':old,'to':stato})
    db.commit()
    return RedirectResponse(f'/manager/cantieri/{site_id}?saved=stato',303)


@router.get('/getti')
def groups(site_id:int, db:Session=Depends(get_db), user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id)
    return [describe(g) for g in db.query(SitePour).filter_by(site_id=site_id).order_by(SitePour.id)]


class GroupInput(BaseModel):
    numbers:list[int]=Field(min_length=2,max_length=20)
    kind:str
    confirm_net:bool=False


@router.post('/getti')
def create(site_id:int, request:Request, body:GroupInput, db:Session=Depends(get_db), user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    try:
        group=create_group(db,site,body.numbers,body.kind,body.confirm_net)
        log_audit_event(db,user,'SITE_POUR_CREATED','site_pour',group.id,describe(group))
        db.commit()
        return describe(group)
    except Exception:
        db.rollback();raise


class CastInput(BaseModel):
    revision:int=Field(ge=1)
    total_m3:FiniteFloat=Field(gt=0,le=100000)
    cast_date:date
    manual:list[FiniteFloat]|None=None
    confirm:bool=False


def locked_group(db,site_id,group_id,revision):
    # Same lock order as fiche saves and PDF approval.
    db.query(Site).filter_by(id=site_id).with_for_update().one()
    g=db.query(SitePour).filter_by(site_id=site_id,id=group_id).populate_existing().first()
    if not g: raise HTTPException(404,'Getto non trovato')
    if g.revision!=revision: raise HTTPException(409,'Il getto è cambiato: ricarica prima di salvare.')
    return g


@router.put('/getti/{group_id}')
def cast(site_id:int,group_id:int,request:Request,body:CastInput,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(db,user,site_id,True);same_origin(request)
    if not body.confirm: raise HTTPException(400,'Conferma la ripartizione del getto.')
    try:
        g=locked_group(db,site_id,group_id,body.revision)
        before=describe(g)
        record_joint(db,g,body.total_m3,body.cast_date,body.manual)
        log_audit_event(db,user,'SITE_POUR_RECORDED','site_pour',g.id,{'before':before,'after':describe(g)})
        db.commit();return describe(g)
    except Exception:
        db.rollback();raise


@router.delete('/getti/{group_id}')
def remove(site_id:int,group_id:int,request:Request,revision:int,confirm:bool=False,delete_fiche:bool=False,
           db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    site=access(db,user,site_id,True);same_origin(request)
    if not confirm: raise HTTPException(400,'Conferma lo scioglimento del gruppo.')
    try:
        g=locked_group(db,site_id,group_id,revision)
        snapshot=describe(g)
        fiches={m.fiche for m in g.members if m.fiche is not None}
        if g.kind=='angle' and fiches and not delete_fiche:
            raise HTTPException(409,'L’angolo contiene una fiche unica: conferma esplicitamente anche la sua eliminazione.')
        if g.kind=='angle' and fiches and not has_perm(user, 'records.delete'):
            raise HTTPException(403,'Solo un amministratore può eliminare la fiche unica dell’angolo.')
        if g.kind=='joint':
            for m in g.members:
                if m.fiche and g.total_m3 is not None:
                    old=json.loads(m.snapshot)
                    m.fiche.metri_cubi_gettati=old['old_volume']
                    m.fiche.data_getto=date.fromisoformat(old['old_date']) if old['old_date'] else None
        db.delete(g);db.flush()
        if g.kind=='angle':
            for f in fiches: db.delete(f)
        db.flush()
        from main import _sync_site_fiche_progress
        _sync_site_fiche_progress(db,site)
        log_audit_event(db,user,'SITE_POUR_REMOVED','site_pour',group_id,snapshot)
        db.commit();return {'removed':True}
    except Exception:
        db.rollback();raise
