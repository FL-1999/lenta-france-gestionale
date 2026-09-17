from sqlalchemy import text
from test_operations import operations
from test_purchasing_workflows import setup
from models import Base, MagazzinoItem, MagazzinoCategoria, MagazzinoMacro, MagazzinoMovimento, Supplier, SupplierArticle, User, RoleEnum
from database import ensure_model_columns


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
