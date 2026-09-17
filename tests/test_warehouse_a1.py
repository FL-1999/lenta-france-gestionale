from sqlalchemy import text
from test_operations import operations
from test_purchasing_workflows import setup
from models import Base, MagazzinoItem, MagazzinoCategoria, MagazzinoMacro, MagazzinoMovimento, Supplier, SupplierArticle, User, RoleEnum
from database import ensure_model_columns


def test_reclassify_existing_article_preserves_identity_stock_and_history(operations):
    from models import PurchaseOrder, PurchaseOrderLine, MagazzinoMovimentoTipoEnum
    db,c,s,item,cat=setup(operations)
    item.categoria_id=None;item.quantita_disponibile=7
    link=SupplierArticle(supplier_id=s.id,codice='VENDOR-7',magazzino_item_id=item.id)
    po=PurchaseOrder(order_number='CLASS-1',supplier_id=s.id)
    db.add_all([link,po]);db.flush()
    line=PurchaseOrderLine(order_id=po.id,description=item.nome,qty_ordered=7,magazzino_item_id=item.id)
    movement=MagazzinoMovimento(item_id=item.id,tipo=MagazzinoMovimentoTipoEnum.carico,quantita=7)
    db.add_all([line,movement]);db.commit()
    code=item.codice;url=f'/manager/magazzino/items/{item.id}/classificazione'
    assert 'Assegna categoria' in c.get(f'/manager/magazzino/items/{item.id}/scheda').text
    assert c.get(url).status_code==200
    assert c.post(url,data={'mode':'existing','category_id':cat.id},follow_redirects=False).status_code==303
    db.refresh(item);assert item.categoria_id==cat.id
    macro=MagazzinoMacro(name='Sollevamento');db.add(macro);db.commit()
    assert c.post(url,data={'mode':'new','category_name':'Ganci','macro_id':macro.id},follow_redirects=False).status_code==303
    db.refresh(item);db.expire(item,['categoria']);assert item.categoria.nome=='Ganci' and item.categoria.macro_id==macro.id
    assert c.post(url,data={'mode':'new','category_name':'Pompe','macro_id':'__new__','macro_name':'Idraulica'},follow_redirects=False).status_code==303
    db.refresh(item);db.expire(item,['categoria']);assert item.categoria.nome=='Pompe' and item.categoria.macro.name=='Idraulica'
    assert c.post(url,data={'mode':'existing','category_id':cat.id},follow_redirects=False).status_code==303
    assert c.post(url,data={'mode':'none'},follow_redirects=False).status_code==303
    db.refresh(item);db.refresh(link);db.refresh(line)
    assert item.categoria_id is None and item.quantita_disponibile==7 and item.codice==code
    assert link.magazzino_item_id==line.magazzino_item_id==item.id
    assert db.query(MagazzinoMovimento).count()==1
    assert db.query(MagazzinoItem).count()==1


def test_classification_validation_is_atomic_and_restricted(operations):
    db,c,s,item,cat=setup(operations)
    macro=MagazzinoMacro(name='Esistente');inactive=MagazzinoCategoria(nome='Inattiva',slug='inattiva',attiva=False)
    db.add_all([macro,inactive]);db.commit()
    url=f'/manager/magazzino/items/{item.id}/classificazione'
    invalid=[{'mode':'existing','category_id':inactive.id}, {'mode':'existing','category_id':'999999'},
             {'mode':'new','category_name':'Nuova','macro_id':'999999'},
             {'mode':'new','category_name':cat.nome.upper(),'macro_id':'__new__','macro_name':'Non creare'},
             {'mode':'new','category_name':'Nuova','macro_id':'__new__','macro_name':macro.name.upper()},
             {'mode':'new','category_name':'x'*256,'macro_id':macro.id}, {'mode':'invalid'}]
    for data in invalid:
        result=c.post(url,data=data)
        assert result.status_code==400,result.text
        db.refresh(item);assert item.categoria_id==cat.id
        assert db.query(MagazzinoCategoria).count()==2 and db.query(MagazzinoMacro).count()==1
    operations['actor'][0]=operations['capo']
    assert c.get(url).status_code==403
    assert c.post(url,data={'mode':'none'}).status_code==403


def test_article_delete_requires_confirmation_and_retains_vendor_catalog(operations):
    from models import AuditLog
    db,c,s,item,cat=setup(operations)
    item_id=item.id;code=item.codice
    link=SupplierArticle(supplier_id=s.id,codice='KEEP-SKU',magazzino_item_id=item_id)
    admin=User(email='delete-admin@example.com',role=RoleEnum.admin,hashed_password='x',is_active=True)
    db.add_all([link,admin]);db.commit();link_id=link.id
    url=f'/manager/magazzino/items/{item_id}/delete-permanent'
    assert c.post(url,data={'confirmed':'true'}).status_code==403
    operations['actor'][0]=admin
    assert c.get(f'/manager/magazzino/items/{item_id}/elimina').status_code==200
    assert db.get(MagazzinoItem,item_id) is not None
    assert c.post(url).status_code==400
    assert c.post(url,data={'confirmed':'false'}).status_code==400
    assert c.post(url,data={'confirmed':'true'},follow_redirects=False).status_code==303
    assert db.get(MagazzinoItem,item_id) is None
    db.expire_all();link=db.get(SupplierArticle,link_id)
    assert link.codice=='KEEP-SKU' and link.magazzino_item_id is None
    assert db.query(AuditLog).filter_by(action='MAGAZZINO_ITEM_DELETE').count()==1
    replacement=MagazzinoItem(nome='Sostituto',attivo=True);db.add(replacement);db.commit()
    assert replacement.codice!=code


def test_article_delete_protects_stock_and_each_type_of_history(operations):
    from models import (PurchaseOrder,PurchaseOrderLine,MagazzinoRichiesta,MagazzinoRichiestaRiga,
                        MagazzinoMovimentoTipoEnum)
    o=operations;db=o['db'];c=o['client']
    admin=User(email='history-admin@example.com',role=RoleEnum.admin,hashed_password='x',is_active=True)
    db.add(admin);db.commit();o['actor'][0]=admin
    for kind in ['stock','movement','order','request']:
        item=MagazzinoItem(nome=kind,attivo=kind!='movement',quantita_disponibile=2 if kind=='stock' else 0)
        db.add(item);db.flush();item_id=item.id
        if kind=='movement':db.add(MagazzinoMovimento(item_id=item_id,tipo=MagazzinoMovimentoTipoEnum.carico,quantita=1))
        if kind=='order':
            po=PurchaseOrder(order_number='KEEP-ORDER');db.add(po);db.flush()
            db.add(PurchaseOrderLine(order_id=po.id,description='Storico',qty_ordered=1,magazzino_item_id=item_id))
        if kind=='request':
            req=MagazzinoRichiesta(richiesto_da_user_id=admin.id);db.add(req);db.flush()
            db.add(MagazzinoRichiestaRiga(richiesta_id=req.id,item_id=item_id,quantita_richiesta=1))
        db.commit()
        result=c.post(f'/manager/magazzino/items/{item_id}/delete-permanent',data={'confirmed':'true'})
        assert result.status_code==(400 if kind=='stock' else 409),result.text
        assert 'name="confirmed"' not in result.text
        db.refresh(item);assert item.quantita_disponibile==(2 if kind=='stock' else 0)
    assert db.query(MagazzinoItem).count()==4
    assert db.query(PurchaseOrderLine).count()==db.query(MagazzinoRichiestaRiga).count()==db.query(MagazzinoMovimento).count()==1


def test_empty_catalog_can_create_macro_and_category_without_order(operations):
    from models import PurchaseOrder
    o=operations;db=o['db'];c=o['client'];o['actor'][0]=o['manager']
    empty=c.get('/manager/magazzino/categorie/nuova')
    assert empty.status_code==200 and 'Crea prima una macro' in empty.text
    assert 'name="macro_id"' not in empty.text
    for path in ['/manager/magazzino','/manager/magazzino/macros','/manager/magazzino/categorie']:
        page=c.get(path)
        assert page.status_code==200 and 'Nuova macro' in page.text and 'Nuova categoria' in page.text
    assert c.post('/manager/magazzino/macro/nuova',data={'name':'Sollevamento'},follow_redirects=False).status_code==303
    macro=db.query(MagazzinoMacro).filter_by(name='Sollevamento').one()
    catalog=c.get('/manager/magazzino')
    assert 'Sollevamento' in catalog.text
    page=c.get('/manager/magazzino',params={'macro_id':macro.id})
    assert f'categorie/nuova?macro_id={macro.id}' in page.text
    form=c.get('/manager/magazzino/categorie/nuova',params={'macro_id':macro.id})
    assert f'<option value="{macro.id}" selected>' in form.text
    result=c.post('/manager/magazzino/categorie/nuova',data={'nome':'Catene','macro_id':macro.id,'attiva':'on'},follow_redirects=False)
    assert result.status_code==303
    category=db.query(MagazzinoCategoria).filter_by(nome='Catene').one()
    assert category.macro_id==macro.id and category.attiva
    assert 'Catene' in c.get('/manager/magazzino',params={'macro_id':macro.id}).text
    assert db.query(PurchaseOrder).count()==db.query(MagazzinoItem).count()==db.query(MagazzinoMovimento).count()==0
    duplicate=c.post('/manager/magazzino/macro/nuova',data={'name':'SOLLEVAMENTO','ordine':'3'})
    assert duplicate.status_code==200 and 'Esiste già una macro' in duplicate.text
    assert duplicate.context['macro'].ordine==3 and db.query(MagazzinoMacro).count()==1
    duplicate_category=c.post('/manager/magazzino/categorie/nuova',data={'nome':'Catene','macro_id':macro.id,'ordine':'4','attiva':'on'})
    assert 'Esiste già una categoria' in duplicate_category.text
    assert duplicate_category.context['categoria'].nome=='Catene'
    assert duplicate_category.context['categoria'].macro_id==str(macro.id)
    o['actor'][0]=o['capo']
    assert c.post('/manager/magazzino/macro/nuova',data={'name':'Vietato'}).status_code==403
    assert c.post('/manager/magazzino/categorie/nuova',data={'nome':'Vietata','macro_id':macro.id}).status_code==403


def test_optional_location_preserves_stock_and_permissions(operations):
    db,c,s,item,cat=setup(operations)
    item.quantita_disponibile=37;db.commit()
    code=item.codice
    url=f'/manager/magazzino/items/{item.id}/posizione'
    assert c.post(url,data={'scaffale':'  B-12  '},follow_redirects=False).status_code==303
    db.refresh(item)
    assert item.ubicazione_zona is None and item.ubicazione_scaffale=='B-12'
    assert c.get(f'/manager/magazzino/items/{item.id}/scheda').status_code==200
    assert c.post(url,data={'zona':'x'*101}).status_code==400
    db.rollback()
    operations['actor'][0]=operations['capo']
    assert c.post(url,data={'remove':'true'}).status_code==403
    db.rollback();db.refresh(item);assert item.ubicazione_scaffale=='B-12'
    keeper=User(email='warehouse@example.com',role=RoleEnum.magazzino,hashed_password='x',is_active=True)
    db.add(keeper);db.commit();operations['actor'][0]=keeper
    assert c.post(url,data={'zona':'Deposito', 'scaffale':'B', 'ripiano':'3'},follow_redirects=False).status_code==303
    assert c.post(url,data={'remove':'true'},follow_redirects=False).status_code==303
    db.refresh(item)
    assert all(getattr(item,field) is None for field in ['ubicazione_zona','ubicazione_scaffale','ubicazione_ripiano'])
    assert item.quantita_disponibile==37 and item.codice==code
    assert db.query(MagazzinoMovimento).count()==0


def test_catalog_filters_and_four_supplier_codes(operations):
    db,c,s,item,cat=setup(operations)
    spare=MagazzinoItem(nome='Pompa libera',quantita_disponibile=5,attivo=True)
    inactive=MagazzinoCategoria(nome='Storica',slug='storica',attiva=False)
    legacy=MagazzinoItem(nome='Pezzo storico',categoria=inactive,attivo=True)
    db.add_all([spare,legacy]);db.commit()
    for n in range(4):
        vendor=Supplier(name=f'Fornitore {n}',is_active=True);db.add(vendor);db.commit()
        assert c.post(f'/manager/magazzino/items/{item.id}/fornitori',data={'supplier_id':vendor.id,'code':f'SKU-{n}'},follow_redirects=False).status_code==303
    assert db.query(SupplierArticle).filter_by(magazzino_item_id=item.id).count()==4
    page=c.get('/manager/magazzino?view=all');assert page.status_code==200
    assert '4 fornitori' in page.text and 'Pompa libera' in page.text
    page=c.get('/manager/magazzino',params={'categoria_id':cat.id})
    assert 'Bullone M12' in page.text and 'Pompa libera' not in page.text
    page=c.get('/manager/magazzino',params={'categoria_id':0})
    assert 'Bullone M12' not in page.text and 'Pompa libera' in page.text and 'Pezzo storico' in page.text
    page=c.get('/manager/magazzino',params={'q':'SKU-3'})
    assert 'Bullone M12' in page.text and 'Pompa libera' not in page.text
    page=c.get('/manager/magazzino',params={'q':'inesistente'})
    assert page.status_code==200 and 'Nessun articolo trovato' in page.text


def test_location_columns_upgrade_existing_inventory(operations):
    db,c,s,item,cat=setup(operations)
    item.quantita_disponibile=12;db.commit();item_id=item.id;code=item.codice
    engine=db.get_bind()
    # Reading expired attributes starts a transaction. Release its PostgreSQL
    # table lock before simulating an older schema on a separate connection.
    db.commit()
    with engine.begin() as conn:
        for field in ['ubicazione_zona','ubicazione_scaffale','ubicazione_ripiano']:
            conn.execute(text(f'ALTER TABLE magazzino_items DROP COLUMN {field}'))
    for _ in range(2): ensure_model_columns(engine,(Base.metadata,))
    db.expire_all();stored=db.get(MagazzinoItem,item_id)
    assert stored.codice==code and stored.quantita_disponibile==12
    assert stored.ubicazione_zona is None and stored.ubicazione_scaffale is None and stored.ubicazione_ripiano is None


def test_macro_category_article_navigation_and_search(operations):
    db,c,s,item,cat=setup(operations)
    macro=MagazzinoMacro(name='Sollevamento')
    other=MagazzinoMacro(name='Lubrificanti')
    second=MagazzinoCategoria(nome='Catene',slug='catene',attiva=True,macro=macro)
    third=MagazzinoCategoria(nome='Oli',slug='oli',attiva=True,macro=other)
    cat.macro=macro
    db.add_all([MagazzinoItem(nome='Catena prova',categoria=second,attivo=True),
                MagazzinoItem(nome='Olio prova',categoria=third,attivo=True)])
    db.commit()
    root=c.get('/manager/magazzino');assert root.status_code==200
    assert 'Sollevamento' in root.text and 'Lubrificanti' in root.text
    assert 'warehouse-row-name' not in root.text
    page=c.get('/manager/magazzino',params={'macro_id':macro.id})
    assert 'Catene' in page.text and 'Bulloneria' in page.text
    assert 'Olio prova' not in page.text and 'warehouse-row-name' not in page.text
    page=c.get('/manager/magazzino',params={'categoria_id':second.id})
    assert 'Catena prova' in page.text and 'Olio prova' not in page.text and 'Bullone M12' not in page.text
    assert 'Sollevamento' in page.text
    page=c.get('/manager/magazzino?view=all')
    assert 'Catena prova' in page.text and 'Olio prova' in page.text and 'Bullone M12' in page.text
    page=c.get('/manager/magazzino',params={'macro_id':macro.id,'view':'all'})
    assert 'Catena prova' in page.text and 'Olio prova' not in page.text
    assert 'Catena prova' in c.get('/manager/magazzino?q=Catena').text
    orphan=MagazzinoCategoria(nome='Senza gruppo',slug='senza-gruppo',attiva=True)
    db.add(MagazzinoItem(nome='Orfano prova',categoria=orphan,attivo=True));db.commit()
    page=c.get('/manager/magazzino?macro_id=0&view=all')
    assert 'Orfano prova' in page.text and 'Catena prova' not in page.text
    assert c.get('/manager/magazzino?macro_id=999999').status_code==404
