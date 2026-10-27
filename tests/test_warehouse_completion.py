from test_operations import operations
from test_purchasing_workflows import setup, order
from test_article_suppliers import create
from models import (MagazzinoItem, MagazzinoMacro, MagazzinoCategoria, Supplier, SupplierArticle,
                    WarehouseSupplierPending, MagazzinoMovimento, User, RoleEnum, PurchaseOrder)
from services.warehouse_completion import summary


def seed(o):
    db,c,vendor,item,category=setup(o)
    category.macro=MagazzinoMacro(name='Ferramenta')
    db.commit()
    return db,c,vendor,item,category


def test_create_known_supplier_without_code_keeps_category_and_stock(operations):
    db,c,vendor,old,category=seed(operations)
    result=create(c,categoria_id=category.id,supplier_ids=[str(vendor.id)],supplier_codes=['   '])
    assert result.status_code==303,result.text
    item=db.query(MagazzinoItem).filter_by(nome='Gancio nuovo').one()
    assert item.categoria_id==category.id and item.quantita_disponibile==8
    assert db.query(SupplierArticle).count()==0
    pending=db.query(WarehouseSupplierPending).one()
    assert (pending.magazzino_item_id,pending.supplier_id)==(item.id,vendor.id)
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).one().quantita==8
    code=item.codice
    card=c.get(result.headers['location'])
    assert card.status_code==200 and 'Codice da aggiungere' in card.text
    assert 'Nessun fornitore collegato' not in card.text
    assert c.get('/manager/magazzino',params={'categoria_id':category.id}).context['supplier_counts'][item.id]==1
    assert item.id not in [i.id for i in c.get('/manager/magazzino?categoria_id=0').context['items']]
    queue=c.get('/manager/magazzino/da-completare?kind=code')
    assert [i.id for i in queue.context['items']]==[item.id]
    assert c.post(f'/manager/magazzino/items/{item.id}/fornitori',data={
        'supplier_id':vendor.id,'code':'REAL-1','return_completion':'true','completion_filter':'code'
    },follow_redirects=False).status_code==303
    assert db.query(WarehouseSupplierPending).count()==0
    assert db.query(SupplierArticle).one().codice=='REAL-1'
    assert not c.get('/manager/magazzino/da-completare?kind=code').context['items']
    db.refresh(item)
    assert item.codice==code and item.categoria_id==category.id and item.quantita_disponibile==8
    assert db.query(MagazzinoItem).count()==2 and db.query(MagazzinoMovimento).count()==1


def test_distinct_counts_existing_articles_and_macro_navigation(operations):
    db,c,vendor,item,cat=seed(operations)
    vendor2=Supplier(name='Secondo',is_active=True)
    mixed=MagazzinoItem(nome='Doppi dati mancanti',attivo=True)
    complete=MagazzinoItem(nome='Completo',attivo=True,categoria=cat)
    archived=MagazzinoItem(nome='Archivio',attivo=False)
    db.add_all([mixed,complete,archived,vendor2]);db.flush()
    db.add_all([SupplierArticle(supplier_id=vendor.id,magazzino_item_id=complete.id,codice='OK'),
        WarehouseSupplierPending(supplier_id=vendor.id,magazzino_item_id=mixed.id),
        WarehouseSupplierPending(supplier_id=vendor2.id,magazzino_item_id=mixed.id)])
    db.commit()
    assert summary(db)=={'all':2,'classification':1,'supplier':1,'code':1}
    home=c.get('/manager/magazzino')
    assert not home.context['show_articles']
    assert 'warehouse-completion-entry' in home.text and 'Ferramenta' in home.text
    for kind,expected in [('all',[item.id,mixed.id]),('classification',[mixed.id]),('supplier',[item.id]),('code',[mixed.id])]:
        page=c.get('/manager/magazzino/da-completare',params={'kind':kind})
        assert page.status_code==200,page.text
        assert sorted(i.id for i in page.context['items'])==sorted(expected)
    assert len(c.get('/manager/magazzino/da-completare?kind=code').context['details'][mixed.id]['pending'])==2
    assert c.get('/manager/magazzino/da-completare?kind=bad').status_code==400
    assert c.get('/manager/magazzino/da-completare?q=Doppi').context['items_count']==1
    # Existing classification updates the same item; code reminders remain.
    assert c.post(f'/manager/magazzino/items/{mixed.id}/classificazione',data={'mode':'existing','category_id':cat.id},follow_redirects=False).status_code==303
    assert summary(db)=={'all':2,'classification':0,'supplier':1,'code':1}


def test_multiple_supplier_codes_only_resolve_the_matching_supplier(operations):
    db,c,vendor,item,cat=seed(operations)
    other=Supplier(name='Altro',is_active=True);db.add(other);db.commit()
    url=f'/manager/magazzino/items/{item.id}/fornitori'
    for sid in [vendor.id,other.id,vendor.id]:
        assert c.post(url,data={'supplier_id':sid},follow_redirects=False).status_code==303
    assert db.query(WarehouseSupplierPending).count()==2
    assert c.post(url,data={'supplier_id':vendor.id,'code':'A'},follow_redirects=False).status_code==303
    assert summary(db)['code']==1
    assert db.query(WarehouseSupplierPending).one().supplier_id==other.id
    # A second known code must not create an extra reminder or item.
    assert c.post(url,data={'supplier_id':vendor.id,'code':'A2'},follow_redirects=False).status_code==303
    assert c.post(url,data={'supplier_id':vendor.id,'code':''},follow_redirects=False).status_code==303
    assert db.query(WarehouseSupplierPending).count()==1
    assert c.post(url,data={'supplier_id':other.id,'code':'B'},follow_redirects=False).status_code==303
    assert summary(db)['all']==0 and db.query(MagazzinoItem).count()==1


def test_conflicting_code_keeps_pending_and_permissions(operations):
    db,c,vendor,item,cat=seed(operations)
    other=MagazzinoItem(nome='Altro',attivo=True,categoria=cat);db.add(other);db.flush()
    db.add(SupplierArticle(supplier_id=vendor.id,magazzino_item_id=other.id,codice='TAKEN'));db.commit()
    url=f'/manager/magazzino/items/{item.id}/fornitori'
    assert c.post(url,data={'supplier_id':vendor.id},follow_redirects=False).status_code==303
    assert c.post(url,data={'supplier_id':vendor.id,'code':'taken'}).status_code==409
    assert db.query(WarehouseSupplierPending).count()==1 and summary(db)['code']==1
    pending=db.query(WarehouseSupplierPending).one()
    remove=f'/manager/magazzino/items/{item.id}/fornitori-in-attesa/{pending.id}/rimuovi'
    for role in [RoleEnum.caposquadra,RoleEnum.magazzino]:
        user=User(email=f'pending-{role.value}@example.com',role=role,is_active=True,hashed_password='x');db.add(user);db.commit()
        operations['actor'][0]=user
        assert c.get('/manager/magazzino/da-completare').status_code==403
        assert c.post(url,data={'supplier_id':vendor.id,'code':'NO'}).status_code==403
        assert c.post(remove).status_code==403
    operations['actor'][0]=operations['manager']
    assert c.post(remove,follow_redirects=False).status_code==303
    assert summary(db)['supplier']==1 and db.query(SupplierArticle).one().magazzino_item_id==other.id


def test_order_completion_and_legacy_codes_refresh_reminders(operations):
    db,c,vendor,item,cat=seed(operations)
    url=f'/manager/magazzino/items/{item.id}/fornitori'
    assert c.post(url,data={'supplier_id':vendor.id},follow_redirects=False).status_code==303
    assert order(operations,vendor,item,cat).status_code==303
    assert db.query(PurchaseOrder).count()==1 and db.query(WarehouseSupplierPending).count()==0
    assert summary(db)['all']==0
    # A legacy/imported code hides stale pending rows even without explicit cleanup.
    db.add(WarehouseSupplierPending(supplier_id=vendor.id,magazzino_item_id=item.id));db.commit()
    assert summary(db)['all']==0
    assert not c.get(f'/manager/magazzino/items/{item.id}/scheda').context['pending_suppliers']


def test_order_without_code_remembers_known_supplier(operations):
    db,c,vendor,item,cat=seed(operations)
    assert order(operations,vendor,item,cat,codice=['']).status_code==303
    assert db.query(SupplierArticle).count()==0
    assert db.query(WarehouseSupplierPending).one().supplier_id==vendor.id
    assert summary(db)=={'all':1,'classification':0,'supplier':0,'code':1}


def test_unclassified_inactive_category_and_missing_macro(operations):
    db,c,vendor,item,cat=seed(operations)
    cat.macro_id=None
    inactive=MagazzinoCategoria(nome='Vecchia',slug='vecchia',attiva=False)
    legacy=MagazzinoItem(nome='Storico',attivo=True,categoria=inactive)
    db.add(legacy);db.commit()
    page=c.get('/manager/magazzino/da-completare?kind=classification')
    assert page.context['items_count']==2
    assert page.context['details'][item.id]['macro_missing']
    assert not page.context['details'][legacy.id]['macro_missing']
    assert 'Assegna macro alla categoria' in page.text and 'Assegna categoria' in page.text


def test_mixed_create_known_and_missing_codes_and_category_prefill(operations):
    db,c,vendor,old,cat=seed(operations)
    page=c.get('/manager/magazzino/nuovo',params={'categoria_id':cat.id})
    assert page.context['default_categoria_id']==cat.id
    assert create(c,supplier_ids=[str(vendor.id),str(vendor.id)],supplier_codes=['','REAL']).status_code==303
    assert db.query(WarehouseSupplierPending).count()==0
    assert db.query(SupplierArticle).one().codice=='REAL'
    assert create(c,nome='Secondo',supplier_ids=[str(vendor.id)]*2,supplier_codes=['','']).status_code==400
