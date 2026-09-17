import pytest
from sqlalchemy import text
from test_operations import operations
from test_purchasing_workflows import setup, order, receive
from test_article_suppliers import create
from models import Base, MagazzinoItem, MagazzinoMovimento, PurchaseOrder
from utils.warehouse_packaging import equivalents


def packaged(c, **changes):
    return create(c, **dict({'nome':'Bentonite','unita_misura':'sacco','packaging_enabled':'true',
        'sacchi_per_bancale':'100','kg_per_sacco':'25','quantita_disponibile':'2','stock_unit':'bancale'}, **changes))


@pytest.mark.parametrize('base,expected',[('sacco',200),('kg',5000),('bancale',2)])
def test_pallet_stock_single_balance_and_movements(operations,base,expected):
    db,c,s,old,cat=setup(operations)
    result=packaged(c,unita_misura=base)
    assert result.status_code==303,result.text
    item=db.query(MagazzinoItem).filter_by(nome='Bentonite').one()
    assert item.quantita_disponibile==expected
    assert equivalents(item)=={'bancale':2,'sacco':200,'kg':5000}
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).one().quantita==expected
    card=c.get(result.headers['location']);assert card.status_code==200 and 'Bancali equivalenti' in card.text
    url=f'/manager/magazzino/items/{item.id}'
    assert c.post(url+'/carico-rapido',data={'quantita':'1','quantity_unit':'bancale'},follow_redirects=False).status_code==303
    assert c.post(url+'/scarico-rapido',data={'quantita':'25','quantity_unit':'kg'},follow_redirects=False).status_code==303
    db.refresh(item)
    assert equivalents(item)['sacco']==pytest.approx(299)
    assert equivalents(item)['kg']==pytest.approx(7475)
    before=item.quantita_disponibile
    c.post(url+'/scarico-rapido',data={'quantita':'1000','quantity_unit':'sacco'})
    db.refresh(item);assert item.quantita_disponibile==before
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).count()==3


@pytest.mark.parametrize('changes',[
    {'sacchi_per_bancale':'0'}, {'sacchi_per_bancale':'2.5'}, {'kg_per_sacco':'-2'},
    {'sacchi_per_bancale':'nan'}, {'kg_per_sacco':'inf'}, {'kg_per_sacco':''},
    {'unita_misura':'pz'}, {'stock_unit':'m'}, {'quantita_disponibile':'nan'},
    {'sacchi_per_bancale':'1000001'}, {'packaging_enabled':'false'},
])
def test_invalid_packaging_rolls_back_preserves_form(operations,changes):
    db,c,*_=setup(operations)
    response=packaged(c,**changes)
    assert response.status_code==400
    assert 'value="Bentonite"' in response.text
    assert db.query(MagazzinoItem).filter_by(nome='Bentonite').count()==0
    assert db.query(MagazzinoMovimento).count()==0


def test_optional_units_edit_equivalences_without_changing_historical_stock(operations):
    db,c,*_=setup(operations)
    for unit in ['bancale','sacco','pz']:
        assert create(c,nome=unit,unita_misura=unit).status_code==303
    assert packaged(c,kg_per_sacco='12,5',sacchi_per_bancale='200').status_code==303
    item=db.query(MagazzinoItem).filter_by(nome='Bentonite').one()
    assert equivalents(item)['kg']==5000
    response=c.post(f'/manager/magazzino/{item.id}/modifica',data={
        'nome':item.nome,'codice':item.codice,'attivo':'true','packaging_form':'true',
        'packaging_enabled':'true','sacchi_per_bancale':'100','kg_per_sacco':'25'},follow_redirects=False)
    assert response.status_code==303
    db.refresh(item);assert item.quantita_disponibile==400 and equivalents(item)['kg']==10000
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).count()==1
    assert c.post(f'/manager/magazzino/{item.id}/modifica',data={
        'nome':item.nome,'codice':item.codice,'attivo':'true','packaging_form':'true',
        'packaging_enabled':'true','sacchi_per_bancale':'0','kg_per_sacco':'25'}).status_code==400
    db.refresh(item);assert item.sacchi_per_bancale==100
    # A legacy client with no packaging fields must not erase the configuration.
    assert c.post(f'/manager/magazzino/{item.id}/modifica',data={
        'nome':item.nome,'codice':item.codice,'attivo':'true'},follow_redirects=False).status_code==303
    db.refresh(item);assert item.sacchi_per_bancale==100


def test_order_receipts_use_base_and_update_all_equivalences(operations):
    db,c,s,old,cat=setup(operations)
    assert packaged(c,quantita_disponibile='0',unita_misura='bancale').status_code==303
    item=db.query(MagazzinoItem).filter_by(nome='Bentonite').one()
    assert order(operations,s,item,cat,qty_ordered=['2']).status_code==303
    po=db.query(PurchaseOrder).one()
    assert receive(c,po,'BANCALI-1',1).status_code==303
    db.refresh(item);assert equivalents(item)=={'bancale':1,'sacco':100,'kg':2500}
    assert receive(c,po,'BANCALI-2',1).status_code==303
    db.refresh(item);assert equivalents(item)=={'bancale':2,'sacco':200,'kg':5000}
    operations['actor'][0]=operations['outsider']
    assert packaged(c).status_code==403


def test_packaging_migration_preserves_existing_stock(operations):
    from database import ensure_model_columns
    db,c,s,item,cat=setup(operations)
    item.quantita_disponibile=12;db.commit()
    engine=db.get_bind()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE magazzino_items DROP COLUMN sacchi_per_bancale'))
        conn.execute(text('ALTER TABLE magazzino_items DROP COLUMN kg_per_sacco'))
    for _ in range(2):ensure_model_columns(engine,(Base.metadata,))
    db.expire_all();db.refresh(item)
    assert item.quantita_disponibile==12 and item.sacchi_per_bancale is None and item.kg_per_sacco is None
    assert equivalents(item)=={}
