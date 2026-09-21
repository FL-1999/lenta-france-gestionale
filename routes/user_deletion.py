from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from auth import get_current_active_user_html
from models import User
from permissions import has_perm
from routes.site_plans import same_origin
from services.user_deletion import references, delete_account

router=APIRouter(prefix='/manager/utenti',tags=['utenti'])


def admin(user=Depends(get_current_active_user_html)):
    if not has_perm(user,'users.delete'): raise HTTPException(403,'Solo un amministratore può eliminare i profili.')
    return user


def show(request, db, actor, target_id, error=None, status_code=200):
    from main import templates, build_template_context
    target=db.get(User,target_id)
    if target is None: raise HTTPException(404,'Profilo non trovato.')
    return templates.TemplateResponse(request,'manager/user_delete.html',build_template_context(
        request,actor,target=target,linked=references(db,target_id),error=error),status_code=status_code)


@router.get('/{user_id}/elimina')
def preview(user_id:int,request:Request,db:Session=Depends(get_db),user=Depends(admin)):
    return show(request,db,user,user_id)


@router.post('/{user_id}/elimina')
def remove(user_id:int,request:Request,conferma_email:str=Form(''),db:Session=Depends(get_db),user=Depends(admin)):
    same_origin(request)
    try:
        delete_account(db,user,user_id,conferma_email)
        db.commit()
    except HTTPException as error:
        db.rollback()
        if error.status_code==404: raise
        return show(request,db,user,user_id,error.detail,error.status_code)
    except IntegrityError:
        db.rollback()
        return show(request,db,user,user_id,'Il profilo è stato collegato ad altri dati. Nessuna cancellazione eseguita; ricarica e verifica.',409)
    return RedirectResponse('/manager/utenti?eliminato=1',303)
