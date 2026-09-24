import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from auth import SECRET_KEY, get_current_active_user_html
from database import get_db
from models import (User, Site, Supplier, CostContract, CostDelivery, CostDeliveryLine,
                    CostInvoice, CostSharedExpense)
from permissions import has_perm
from template_context import render_template, register_manager_badges
from services import site_costs as svc

router=APIRouter(tags=['costs'])
templates=Jinja2Templates(directory='templates')
register_manager_badges(templates)


def token(user):
    value=f'{user.id}:{int(time.time())}:{secrets.token_hex(12)}'
    return value+':'+hmac.new(SECRET_KEY.encode(),('site-cost:'+value).encode(),hashlib.sha256).hexdigest()


def access(user,manage=False):
    if not has_perm(user,'economics.manage' if manage else 'economics.read'):
        raise HTTPException(403,'Permessi insufficienti / Autorisations insuffisantes')


def validate(request,user):
    access(user,True)
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.url.netloc:
        raise HTTPException(403,'Origine non valida / Origine invalide')
    try:
        uid,stamp,nonce,sig=request.headers.get('x-csrf-token','').split(':')
        expected=hmac.new(SECRET_KEY.encode(),f'site-cost:{uid}:{stamp}:{nonce}'.encode(),hashlib.sha256).hexdigest()
        valid=uid==str(user.id) and 0<=time.time()-int(stamp)<=7200 and hmac.compare_digest(sig,expected)
    except (ValueError,TypeError): valid=False
    if not valid:
        raise HTTPException(403,'Ricarica la pagina / Actualisez la page')


def site_row(db,sid,lock=False):
    q=db.query(Site).filter_by(id=sid)
    if lock: q=q.with_for_update()
    row=q.first()
    if not row: raise HTTPException(404,'Cantiere non trovato / Chantier introuvable')
    return row


@router.get('/manager/cantieri/{site_id}/costi',name='site_cost_workspace')
def page(site_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(user)
    return render_template(templates,request,'manager/site_costs.html',dict(site=site_row(db,site_id),
        csrf=token(user),can_edit=has_perm(user,'economics.manage')),db,user)


@router.get('/manager/cantieri/{site_id}/costi/data')
def state(site_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    access(user); site=site_row(db,site_id)
    live={s['key']:s for s in svc.sources(db,site)}
    deliveries=[svc.serialize_delivery(d,live.get(d.source_key)) for d in db.query(CostDelivery).filter_by(site_id=site_id).order_by(CostDelivery.delivery_date.desc(),CostDelivery.id.desc())]
    eligible=[]
    for d in db.query(CostDelivery).filter(CostDelivery.site_id.isnot(None)).order_by(CostDelivery.delivery_date,CostDelivery.id):
        if d.source_snapshot.get('kind')=='warehouse': continue
        for l in d.lines:
            if not l.invoice_id and l.ticket:
                eligible.append(dict(id=l.id,delivery_id=d.id,revision=d.revision,site_id=d.site_id,site_name=d.site_name,
                    supplier_id=d.supplier_id,date=d.delivery_date.isoformat(),label=d.label,ticket=l.ticket,
                    quantity=float(l.quantity),unit=l.unit,unit_price=float(l.unit_price) if l.unit_price is not None else None,extra=float(l.extra)))
    invoices=[]
    for i in db.query(CostInvoice).order_by(CostInvoice.id.desc()).limit(200):
        lines=db.query(CostDeliveryLine).filter_by(invoice_id=i.id).all()
        invoices.append(dict(id=i.id,supplier_id=i.supplier_id,number=i.number,date=i.invoice_date.isoformat(),
            total=float(i.total),revision=i.revision,status=i.status,lines=[dict(site=l.delivery.site_name,
                ticket=l.ticket,delivered=float(l.quantity),invoiced=float(l.invoice_quantity),
                price=float(l.invoice_unit_price),extra=float(l.invoice_extra),amount=float(svc.line_amount(l)),reason=l.invoice_reason) for l in lines]))
    shared=[]
    for e in db.query(CostSharedExpense).order_by(CostSharedExpense.id.desc()).limit(200):
        shared.append(dict(id=e.id,description=e.description,date=e.expense_date.isoformat(),total=float(e.total),revision=e.revision,
            allocations=[dict(site_id=a.site_id,site_name=a.site_name,amount=float(a.amount)) for a in e.allocations]))
    return dict(sources=list(live.values()),deliveries=deliveries,
        contracts=[dict(id=c.id,supplier_id=c.supplier_id,revision=c.revision,**c.payload) for c in db.query(CostContract).filter_by(site_id=site_id)],
        suppliers=[dict(id=s.id,name=s.name or s.legal_name or str(s.id)) for s in db.query(Supplier).order_by(Supplier.name)],
        sites=[dict(id=s.id,name=s.name) for s in db.query(Site).order_by(Site.name)],eligible=eligible,invoices=invoices,shared=shared)


@router.post('/manager/cantieri/{site_id}/costi/{action}')
async def mutate(site_id:int,action:str,request:Request,db:Session=Depends(get_db),user:User=Depends(get_current_active_user_html)):
    validate(request,user)
    try:
        data=await request.json()
        if not isinstance(data,dict): raise ValueError()
    except ValueError:
        raise HTTPException(400,'Dati non validi / Données invalides')
    try:
        # Invoice routines acquire supplier then sites in consistent order.
        site=site_row(db,site_id,lock=action in ('contract','delivery','unverify-delivery'))
        if action=='contract': row=svc.save_contract(db,site,data,user)
        elif action=='delivery': row=svc.save_delivery(db,site,data,user)
        elif action=='unverify-delivery': row=svc.unverify_delivery(db,site,data,user)
        elif action=='invoice': row=svc.save_invoice(db,data,user)
        elif action=='cancel-invoice':
            i=db.get(CostInvoice,data.get('id'))
            if not i: raise HTTPException(404,'Fattura non trovata / Facture introuvable')
            db.query(Supplier).filter_by(id=i.supplier_id).with_for_update().one()
            row=db.query(CostInvoice).filter_by(id=i.id).populate_existing().with_for_update().one()
            svc.cancel_invoice(db,row,data,user)
        elif action=='shared': row=svc.save_shared(db,data,user)
        else: raise HTTPException(404)
        db.commit()
        return {'ok':True,'id':row.id}
    except HTTPException:
        db.rollback(); raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Salvataggio già effettuato o dati cambiati. Ricarica. / Enregistrement déjà effectué ou données modifiées. Actualisez.')
