import pytest
from test_operations import operations
from test_purchasing_workflows import setup
from test_order_line_classification import payload
from models import Supplier,SupplierArticle,MagazzinoItem,MagazzinoMovimento,PurchaseOrder


def create(c,**changes):
    data={'nome':'Gancio nuovo','attivo':'on','unita_misura':'pz','quantita_disponibile':'8'}
    data.update(changes)
    return c.post('/manager/magazzino/nuovo',data=data,follow_redirects=False)


def test_create_article_with_four_suppliers_search_and_order_prefill(operations):
    db,c,s,old,cat=setup(operations)
    vendors=[s]+[Supplier(name=f'Altro {n}',is_active=True) for n in range(3)]
    db.add_all(vendors);db.commit()
    result=create(c,categoria_id=str(cat.id),supplier_ids=[str(v.id) for v in vendors],supplier_codes=['AAA','BBB','CCC','DDD'])
    assert result.status_code==303
    item=db.query(MagazzinoItem).filter_by(nome='Gancio nuovo').one()
    assert item.codice.isdigit() and len(item.codice)>=6 and item.quantita_disponibile==8
    links=db.query(SupplierArticle).filter_by(magazzino_item_id=item.id).all()
    assert len(links)==4
    assert db.query(MagazzinoMovimento).filter_by(item_id=item.id).one().quantita==8
    assert db.query(PurchaseOrder).count()==0
    for code in [item.codice,'AAA','DDD','Gancio nuovo']:
        page=c.get('/manager/magazzino',params={'q':code})
        assert 'Gancio nuovo' in page.text and 'Bullone M12' not in page.text
    page=c.get('/manager/ordini/nuovo',params={'supplier_id':s.id,'item_id':item.id,'supplier_article_id':links[0].id})
    assert page.context['form_data']['lines'][0]['magazzino_item_id']==str(item.id)
    assert page.context['form_data']['lines'][0]['codice']=='AAA'
    assert 'Ordina articolo' in c.get(result.headers['location']).text


def test_optional_suppliers_and_link_later(operations):
    db,c,s,old,cat=setup(operations)
    assert create(c,quantita_disponibile='0').status_code==303
    item=db.query(MagazzinoItem).filter_by(nome='Gancio nuovo').one()
    assert db.query(SupplierArticle).filter_by(magazzino_item_id=item.id).count()==0
    assert db.query(MagazzinoMovimento).count()==0
    result=c.post('/manager/ordini/nuovo',data=payload(operations,s,[{
        'description':item.nome,'qty_ordered':'2','magazzino_item_id':item.id,'codice':''}]),follow_redirects=False)
    assert result.status_code==303
    assert db.query(PurchaseOrder).one().lines[0].magazzino_item_id==item.id
    assert db.query(SupplierArticle).count()==0
    assert item.quantita_disponibile==0
    assert c.post(f'/manager/magazzino/items/{item.id}/fornitori',data={'supplier_id':s.id,'code':'LATER'},follow_redirects=False).status_code==303
    assert db.query(SupplierArticle).one().magazzino_item_id==item.id


@pytest.mark.parametrize('kind',['incomplete','mismatch','duplicate','conflict','inactive'])
def test_supplier_validation_is_atomic_and_preserves_form(operations,kind):
    db,c,s,item,cat=setup(operations)
    other=Supplier(name='Secondo',is_active=True);db.add(other);db.commit()
    ids=[str(other.id),str(s.id)];codes=['VALID','SECOND']
    if kind=='incomplete':codes[1]=''
    if kind=='mismatch':codes.pop()
    if kind=='duplicate':ids[1]=str(other.id);codes[1]='valid'
    if kind=='conflict':db.add(SupplierArticle(supplier_id=s.id,codice='second',magazzino_item_id=item.id));db.commit()
    if kind=='inactive':s.is_active=False;db.commit()
    result=create(c,supplier_ids=ids,supplier_codes=codes)
    assert result.status_code==(409 if kind=='conflict' else 400)
    assert 'value="Gancio nuovo"' in result.text and 'value="VALID"' in result.text
    assert db.query(MagazzinoItem).filter_by(nome='Gancio nuovo').count()==0
    assert db.query(MagazzinoMovimento).count()==0
    assert db.query(SupplierArticle).filter_by(codice='VALID').count()==0


def test_claim_unlinked_catalog_code_and_permissions(operations):
    db,c,s,item,cat=setup(operations)
    legacy=SupplierArticle(supplier_id=s.id,codice='HIST',descrizione='Storico');db.add(legacy);db.commit()
    assert create(c,supplier_ids=[str(s.id)],supplier_codes=['hist']).status_code==303
    db.refresh(legacy)
    assert legacy.magazzino_item_id!=item.id and legacy.descrizione=='Storico'
    assert db.query(SupplierArticle).count()==1
    operations['actor'][0]=operations['outsider']
    assert create(c,supplier_ids=[str(s.id)],supplier_codes=['NO']).status_code==403
