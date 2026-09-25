from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from auth import get_current_active_user_html
from database import get_db
from models import Supplier, SupplierService, ServiceRecord, Site, Veicolo, Machine
from routes.site_costs import token, validate, access
from services import supplier_services as svc
from template_context import render_template, register_manager_badges

router = APIRouter(tags=['supplier-services'])
templates = Jinja2Templates(directory='templates')
register_manager_badges(templates)


@router.get('/manager/servizi', name='supplier_services_workspace')
def page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user)
    return render_template(templates, request, 'manager/supplier_services.html', {'csrf': token(user)}, db, user)


@router.get('/manager/servizi/data')
def data(db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    access(user)
    return dict(
        suppliers=[dict(id=s.id, name=s.name or s.legal_name, active=s.is_active) for s in db.query(Supplier).order_by(Supplier.name)],
        sites=[dict(id=s.id, name=s.name) for s in db.query(Site).order_by(Site.name)],
        vehicles=[dict(id=v.id, name=f'{v.marca} {v.modello} · {v.targa}') for v in db.query(Veicolo).order_by(Veicolo.targa)],
        machines=[dict(id=m.id, name=m.name) for m in db.query(Machine).order_by(Machine.name)],
        offerings=[dict(**s.payload, id=s.id, revision=s.revision, active=s.active) for s in db.query(SupplierService).order_by(SupplierService.id)],
        records=[dict(**{**r.payload, 'site_id': r.site_id, 'vehicle_id': r.vehicle_id, 'machine_id': r.machine_id}, id=r.id, revision=r.revision, amount=str(r.amount)) for r in db.query(ServiceRecord).order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc())])


@router.post('/manager/servizi/{action}')
async def save(action: str, request: Request, db: Session = Depends(get_db), user=Depends(get_current_active_user_html)):
    validate(request, user)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Dati non validi / Données invalides')
    try:
        if action == 'catalogue':
            row = svc.save_offering(db, data, user)
        elif action == 'record':
            row = svc.save_record(db, data, user)
        else:
            raise HTTPException(404)
        db.commit()
        return dict(id=row.id, revision=row.revision)
    except HTTPException:
        db.rollback(); raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Dati cambiati o registrazione già salvata. Ricarica. / Données modifiées ou déjà sauvegardées. Actualisez.')
