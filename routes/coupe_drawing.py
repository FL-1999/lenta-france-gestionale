import json
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from auth import get_current_active_user_html
from database import get_db
from routes.site_plans import access, same_origin
from services.coupe_drawing import read_pdf
from services.site_plan_import import MAX_PDF_BYTES

router = APIRouter(tags=['coupe PDF'])


@router.post('/manager/cantieri/{site_id}/coupe/leggi-pdf')
def read(site_id: int, request: Request, file: UploadFile = File(...),
         page_number: int = Form(1), crop: str = Form(''),
         db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(db, user, site_id, edit=True)
    same_origin(request)
    # Custom header prevents cross-site form submissions. This endpoint only reads.
    if request.headers.get('x-coupe-reader') != '1':
        raise HTTPException(403, 'Ricarica la pagina / Actualisez la page')
    try:
        region = json.loads(crop) if crop else None
        return read_pdf(file.file.read(MAX_PDF_BYTES+1), page_number, region)
    except ValueError as exc:
        raise HTTPException(400, str(exc) or 'Dati non validi / Données invalides') from exc
