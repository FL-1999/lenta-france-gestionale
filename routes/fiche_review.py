from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from auth import get_current_active_user_html
from database import get_db
from models import Fiche, User
from services.fiche_review import confirm_fiche

router = APIRouter()


@router.post('/manager/fiches/{fiche_id}/conferma')
def confirm(fiche_id: int, request: Request, csrf: str = Form(..., max_length=64),
            db: Session = Depends(get_db), user: User = Depends(get_current_active_user_html)):
    fiche = db.get(Fiche, fiche_id)
    if not fiche:
        raise HTTPException(404, 'Fiche non trovata')
    confirm_fiche(db, fiche, user, csrf, request)
    return RedirectResponse(f'/manager/fiches/{fiche_id}', status_code=303)
