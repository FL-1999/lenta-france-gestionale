"""Supplier contacts and the cross-reference between vendor SKUs and one stock item."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from auth import get_current_active_user_html
from database import get_db
from models import Supplier, SupplierArticle, SupplierContact, MagazzinoItem, MagazzinoMovimento, User, PurchaseOrder, PurchaseOrderLine
from permissions import has_perm, can_access_warehouse_area, can_manage_warehouse_requests
from utils.places import get_selectable_places
from models import RoleEnum
from template_context import register_manager_badges, render_template
from audit_utils import log_audit_event

router=APIRouter(tags=['catalogo acquisti'])
templates=Jinja2Templates(directory='templates')
register_manager_badges(templates)


def manager(user):
    if not has_perm(user,'manager.access'):
        raise HTTPException(403,'Permessi insufficienti')


@router.post('/manager/fornitori/{supplier_id}/referenti', name='supplier_contact_save')
def contact_save(supplier_id:int, request:Request, contact_id:int=Form(0), name:str=Form(...),
                 email:str=Form(''), phone:str=Form(''), role_label:str=Form(''), active:bool=Form(False),
                 db:Session=Depends(get_db), current_user:User=Depends(get_current_active_user_html)):
    manager(current_user)
    supplier=db.get(Supplier,supplier_id)
    if not supplier: raise HTTPException(404,'Fornitore non trovato')
    if not name.strip(): raise HTTPException(400,'Inserisci il nome del referente')
    if email.strip() and ('@' not in email or any(c in email for c in '\r\n')):
        raise HTTPException(400,'Email non valida')
    contact=db.get(SupplierContact,contact_id) if contact_id else SupplierContact(supplier_id=supplier_id)
    if not contact or contact.supplier_id!=supplier_id: raise HTTPException(404,'Referente non trovato')
    contact.name=name.strip();contact.email=email.strip() or None;contact.phone=phone.strip() or None
    contact.role_label=role_label.strip() or None;contact.is_active=active
    db.add(contact);db.flush()
    log_audit_event(db,current_user,'SUPPLIER_CONTACT_SAVE','supplier_contact',contact.id,{'supplier_id':supplier_id})
    db.commit()
    return RedirectResponse(str(request.url_for('manager_fornitori_edit',supplier_id=supplier_id))+'#referenti',303)


@router.get('/manager/magazzino/items/{item_id}/scheda',name='warehouse_item_card')
def item_card(item_id:int,request:Request,db:Session=Depends(get_db),current_user:User=Depends(get_current_active_user_html)):
    if not can_access_warehouse_area(current_user): raise HTTPException(403,'Permessi insufficienti')
    item=db.get(MagazzinoItem,item_id)
    if not item: raise HTTPException(404,'Articolo non trovato')
    return _render_item_card(request,db,current_user,item)


def _render_item_card(request,db,current_user,item,*,error_message=None,supplier_form=None,status_code=200):
    return render_template(templates,request,'manager/magazzino/item_card.html',{
        'error_message':error_message,'supplier_form':supplier_form or {},
        'item':item,'can_edit_catalog':has_perm(current_user,'manager.access'),
        'can_handle_stock':can_manage_warehouse_requests(current_user),
        'can_edit_location':has_perm(current_user,'manager.access') or has_perm(current_user,'inventory.manage'),
        'locations':get_selectable_places(db, include_inactive=False),
        'personale':db.query(User).filter(User.is_active.is_(True),User.role.notin_([RoleEnum.admin,RoleEnum.manager])).order_by(User.full_name,User.email).all(),
        'supplier_articles':db.query(SupplierArticle).options(joinedload(SupplierArticle.supplier)).filter_by(magazzino_item_id=item.id).all(),
        'suppliers':db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all(),
        'movements':db.query(MagazzinoMovimento).filter_by(item_id=item.id).order_by(MagazzinoMovimento.id.desc()).limit(50).all(),
    },db,current_user,status_code=status_code)


@router.post('/manager/magazzino/items/{item_id}/posizione',name='warehouse_item_location_save')
def save_location(item_id:int,request:Request,zona:str=Form(''),scaffale:str=Form(''),ripiano:str=Form(''),
                  remove:bool=Form(False),db:Session=Depends(get_db),
                  current_user:User=Depends(get_current_active_user_html)):
    if not (has_perm(current_user,'manager.access') or has_perm(current_user,'inventory.manage')):
        raise HTTPException(403,'Permessi insufficienti')
    item=db.query(MagazzinoItem).filter_by(id=item_id).with_for_update().first()
    if not item: raise HTTPException(404,'Articolo non trovato')
    fields=('ubicazione_zona','ubicazione_scaffale','ubicazione_ripiano')
    values=[None,None,None] if remove else [v.strip() or None for v in (zona,scaffale,ripiano)]
    if any(v and len(v)>100 for v in values):
        raise HTTPException(400,'Ogni campo posizione può contenere al massimo 100 caratteri')
    before={field:getattr(item,field) for field in fields}
    for field,value in zip(fields,values): setattr(item,field,value)
    log_audit_event(db,current_user,'WAREHOUSE_LOCATION_SAVE','magazzino_item',item.id,
                    {'before':before,'after':dict(zip(fields,values))})
    db.commit()
    return RedirectResponse(str(request.url_for('warehouse_item_card',item_id=item_id))+'?saved=location#posizione',303)


@router.post('/manager/magazzino/items/{item_id}/fornitori',name='warehouse_item_supplier_link')
def link_supplier(item_id:int,request:Request,supplier_id:int=Form(...),code:str=Form(...),
                  db:Session=Depends(get_db),current_user:User=Depends(get_current_active_user_html)):
    manager(current_user)
    supplier=db.query(Supplier).filter_by(id=supplier_id).with_for_update().first()
    item=db.get(MagazzinoItem,item_id)
    if not item: raise HTTPException(404,'Articolo non trovato')
    def invalid(message,status=400):
        db.rollback()
        return _render_item_card(request,db,current_user,item,error_message=message,
                                 supplier_form={'supplier_id':supplier_id,'code':code},status_code=status)
    if not supplier or not supplier.is_active or not item.attivo:
        return invalid('Fornitore o articolo non disponibile')
    code=code.strip()
    if not code or len(code)>100: return invalid('Codice fornitore non valido')
    matches=db.query(SupplierArticle).filter(SupplierArticle.supplier_id==supplier_id,func.lower(SupplierArticle.codice)==code.lower()).all()
    if len(matches)>1: return invalid('Esistono più codici storici equivalenti: correggi il catalogo prima di collegarli',409)
    article=matches[0] if matches else None
    if article and article.magazzino_item_id not in (None,item_id):
        return invalid('Questo codice fornitore è già collegato a un altro articolo interno',409)
    if not article:
        article=SupplierArticle(supplier_id=supplier_id,codice=code,descrizione=item.nome,unita=item.unita_misura)
    article.magazzino_item_id=item_id;db.add(article);db.flush()
    log_audit_event(db,current_user,'SUPPLIER_ARTICLE_LINK','supplier_article',article.id,{'item_id':item_id,'supplier_id':supplier_id,'code':code})
    db.commit()
    return RedirectResponse(str(request.url_for('warehouse_item_card',item_id=item_id))+'#fornitori',303)


@router.post('/manager/ordini/{order_id}/righe/{line_id}/articolo',name='purchase_line_link')
def link_purchase_line(order_id:int,line_id:int,request:Request,item_id:int=Form(...),
                       db:Session=Depends(get_db),current_user:User=Depends(get_current_active_user_html)):
    manager(current_user)
    order=db.query(PurchaseOrder).filter_by(id=order_id).populate_existing().with_for_update().first()
    line=db.get(PurchaseOrderLine,line_id)
    item=db.get(MagazzinoItem,item_id)
    if not order or not line or line.order_id!=order_id or not item or not item.attivo:
        raise HTTPException(404,'Ordine o articolo non trovato')
    if line.magazzino_item_id is not None:
        raise HTTPException(409,'La riga ha già un articolo: non si modifica il collegamento storico')
    if any(dl.delivery.confirmed for dl in line.delivery_lines):
        raise HTTPException(409,'La riga contiene consegne confermate: richiede una verifica dello storico')
    if line.codice and order.supplier_id:
        db.query(Supplier).filter_by(id=order.supplier_id).with_for_update().first()
        matches=db.query(SupplierArticle).filter(SupplierArticle.supplier_id==order.supplier_id,
            func.lower(SupplierArticle.codice)==line.codice.lower()).all()
        if len(matches)>1 or (matches and matches[0].magazzino_item_id not in (None,item.id)):
            raise HTTPException(409,'Codice fornitore già associato a un altro articolo o ambiguo')
        article=matches[0] if matches else SupplierArticle(supplier_id=order.supplier_id,codice=line.codice,descrizione=line.description)
        article.magazzino_item_id=item.id;db.add(article)
    line.magazzino_item_id=item.id
    log_audit_event(db,current_user,'PURCHASE_LINE_LINK','purchase_order_line',line.id,{'item_id':item.id})
    db.commit()
    return RedirectResponse(request.url_for('manager_ordini_detail',order_id=order.id),303)


def _classification_form(request, db, user, item, values=None, error=None, status=200):
    from models import MagazzinoCategoria, MagazzinoMacro
    return render_template(templates, request, 'manager/magazzino/item_classification.html', {
        'item': item, 'error_message': error,
        'values': values if values is not None else {'mode': 'existing', 'category_id': str(item.categoria_id or '')},
        'categories': db.query(MagazzinoCategoria).options(joinedload(MagazzinoCategoria.macro)).filter_by(attiva=True).order_by(MagazzinoCategoria.nome).all(),
        'macros': db.query(MagazzinoMacro).order_by(MagazzinoMacro.name).all(),
    }, db, user, status_code=status)


@router.get('/manager/magazzino/items/{item_id}/classificazione', name='warehouse_item_classification')
def item_classification(item_id: int, request: Request, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_active_user_html)):
    manager(current_user)
    item = db.get(MagazzinoItem, item_id)
    if not item: raise HTTPException(404, 'Articolo non trovato')
    return _classification_form(request, db, current_user, item)


@router.post('/manager/magazzino/items/{item_id}/classificazione', name='warehouse_item_classification_save')
def save_classification(item_id: int, request: Request, mode: str = Form('existing'),
        category_id: str = Form(''), macro_id: str = Form(''), category_name: str = Form(''),
        macro_name: str = Form(''), db: Session = Depends(get_db),
        current_user: User = Depends(get_current_active_user_html)):
    from models import MagazzinoCategoria, MagazzinoMacro
    from sqlalchemy.exc import IntegrityError
    from template_context import get_lang_from_request, invalidate_manager_badges_cache
    from uuid import uuid4
    manager(current_user)
    item = db.query(MagazzinoItem).filter_by(id=item_id).populate_existing().with_for_update().first()
    if not item: raise HTTPException(404, 'Articolo non trovato')
    values = dict(mode=mode, category_id=category_id, macro_id=macro_id,
                  category_name=category_name, macro_name=macro_name)
    fr = get_lang_from_request(request) == 'fr'
    def fail(it, french):
        raise ValueError(french if fr else it)
    try:
        previous = item.categoria_id
        category = None
        if mode == 'existing':
            category = db.query(MagazzinoCategoria).filter_by(id=int(category_id) if category_id.isdigit() else 0, attiva=True).with_for_update().first()
            if not category: fail('Seleziona una categoria attiva.', 'Sélectionnez une catégorie active.')
        elif mode == 'new':
            name = category_name.strip()
            if not name or len(name)>255: fail('Inserisci un nome categoria (massimo 255 caratteri).', 'Indiquez un nom de catégorie (255 caractères maximum).')
            if db.query(MagazzinoCategoria.id).filter(func.lower(MagazzinoCategoria.nome)==name.lower()).first():
                fail('Esiste già una categoria con questo nome: selezionala tra quelle esistenti.', 'Cette catégorie existe déjà : sélectionnez-la dans la liste.')
            if macro_id == '__new__':
                macro_title = macro_name.strip()
                if not macro_title or len(macro_title)>120: fail('Inserisci un nome macro (massimo 120 caratteri).', 'Indiquez un nom de macro (120 caractères maximum).')
                if db.query(MagazzinoMacro.id).filter(func.lower(MagazzinoMacro.name)==macro_title.lower()).first():
                    fail('Questa macro esiste già: selezionala dalla lista.', 'Cette macro existe déjà : sélectionnez-la dans la liste.')
                macro = MagazzinoMacro(name=macro_title)
                db.add(macro); db.flush()
                log_audit_event(db,current_user,'MACRO_CREATE','MagazzinoMacro',macro.id,{'name':macro.name})
            else:
                macro = db.query(MagazzinoMacro).filter_by(id=int(macro_id) if macro_id.isdigit() else 0).with_for_update().first()
                if not macro: fail('Seleziona una macro o creane una nuova.', 'Sélectionnez une macro ou créez-en une.')
            category = MagazzinoCategoria(nome=name, slug='categoria-'+uuid4().hex, macro_id=macro.id,
                                         attiva=True, icon=macro.icon, color=macro.color)
            db.add(category); db.flush()
            log_audit_event(db,current_user,'CATEGORIA_CREATE','MagazzinoCategoria',category.id,{'nome':name,'macro_id':macro.id})
        elif mode != 'none':
            fail('Scegli una modalità valida.', 'Choisissez une option valide.')
        item.categoria_id = category.id if category else None
        log_audit_event(db,current_user,'WAREHOUSE_CLASSIFICATION_SAVE','MagazzinoItem',item.id,
                        {'before':previous,'after':item.categoria_id})
        db.commit()
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        error = str(exc) if isinstance(exc,ValueError) else ('Classification modifiée entre-temps. Vérifiez les choix et réessayez.' if fr else 'La classificazione è cambiata nel frattempo. Verifica le scelte e riprova.')
        return _classification_form(request,db,current_user,item,values,error,400)
    invalidate_manager_badges_cache()
    return RedirectResponse(str(request.url_for('warehouse_item_card',item_id=item.id))+'?saved=classification',303)
