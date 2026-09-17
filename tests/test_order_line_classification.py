import pytest
from test_operations import operations
from test_purchasing_workflows import setup
from models import (MagazzinoItem,MagazzinoMacro,MagazzinoCategoria,SupplierArticle,
                    PurchaseOrder,MagazzinoMovimento,Site)


def payload(o,s,rows,**extras):
    fields=['codice','description','qty_ordered','magazzino_item_id','line_category_mode',
            'line_category_id','line_macro_id','line_new_category','line_new_macro','line_unit']
    return {'supplier_id':s.id,'order_date':'2026-09-17','requester_user_id':o['manager'].id,
            'order_kind':'warehouse','classification_scope':'line',
            **{f:[str(r.get(f,'')) for r in rows] for f in fields},**extras}


def rows_for(o):
    db,c,s,item,cat=setup(o)
    macro=MagazzinoMacro(name='Sollevamento');db.add(macro);db.flush();cat.macro_id=macro.id
    db.add(SupplierArticle(supplier_id=s.id,codice='KNOWN',magazzino_item_id=item.id));db.commit()
    rows=[{'codice':'KNOWN','description':'Bullone M12','qty_ordered':'2','magazzino_item_id':item.id},
          {'codice':'HOOK','description':'Gancio D13','qty_ordered':'4','magazzino_item_id':'__new__','line_category_mode':'existing','line_category_id':cat.id,'line_unit':'pz'},
          {'codice':'CHAIN','description':'Catena','qty_ordered':'12','magazzino_item_id':'__new__','line_category_mode':'new_in_macro','line_macro_id':macro.id,'line_new_category':'Catene','line_unit':'m'},
          {'codice':'OIL','description':'Olio','qty_ordered':'20','magazzino_item_id':'__new__','line_category_mode':'new_macro','line_new_macro':'Lubrificanti','line_new_category':'Oli','line_unit':'l'}]
    return db,c,s,item,cat,macro,rows


@pytest.mark.parametrize('kind',['warehouse','closed'])
def test_mixed_order_creates_each_classification_and_keeps_site(operations,kind):
    db,c,s,item,cat,macro,rows=rows_for(operations)
    response=c.post('/manager/ordini/nuovo',data=payload(operations,s,rows,order_kind=kind,site_id=str(operations['site'].id)),follow_redirects=False)
    assert response.status_code==303,response.text
    order=db.query(PurchaseOrder).one()
    assert len(order.lines)==4 and order.warehouse_category_id is None
    assert order.lines[0].magazzino_item_id==item.id
    assert order.lines[1].magazzino_item.categoria_id==cat.id
    assert order.lines[2].magazzino_item.categoria.nome=='Catene'
    assert order.lines[2].magazzino_item.categoria.macro_id==macro.id
    assert order.lines[2].magazzino_item.unita_misura=='m'
    assert order.lines[3].magazzino_item.categoria.macro.name=='Lubrificanti'
    assert order.lines[3].magazzino_item.unita_misura=='l'
    assert db.query(SupplierArticle).filter_by(supplier_id=s.id).count()==4
    assert all(l.magazzino_item.quantita_disponibile==0 for l in order.lines)
    assert order.site_id==(operations['site'].id if kind=='closed' else None)
    assert order.delivery_site_id==order.site_id
    assert order.delivery_type==('SITE' if kind=='closed' else 'PICKUP')
    if kind=='warehouse':
        for number,quantities in [('PART',[1,2,6,10]),('FINAL',[1,2,6,10])]:
            result=c.post(f'/manager/ordini/{order.id}/bolle/nuova',data={'delivery_number':number,'delivery_date':'2026-09-17',
                'order_line_id':[l.id for l in order.lines],'qty_delivered':quantities,'confirm_now':'true'},follow_redirects=False)
            assert result.status_code==303,result.text
        db.expire_all();assert order.status=='CHIUSO'
        assert [l.magazzino_item.quantita_disponibile for l in order.lines]==[2,4,12,20]
        assert db.query(MagazzinoMovimento).count()==8


def test_new_categories_are_reused_across_rows_and_duplicate_codes_not_duplicated(operations):
    db,c,s,item,cat,macro,rows=rows_for(operations)
    rows=[rows[3],{**rows[3]}, {**rows[3],'description':'Grasso','codice':'GREASE'}]
    result=c.post('/manager/ordini/nuovo',data=payload(operations,s,rows),follow_redirects=False)
    assert result.status_code==303,result.text
    order=db.query(PurchaseOrder).one()
    assert order.lines[0].magazzino_item_id==order.lines[1].magazzino_item_id
    assert order.lines[2].magazzino_item_id!=order.lines[0].magazzino_item_id
    assert db.query(MagazzinoMacro).filter_by(name='Lubrificanti').count()==1
    assert db.query(MagazzinoCategoria).filter_by(nome='Oli').count()==1


@pytest.mark.parametrize('bad', ['missing_category','invalid_unit','invalid_site','duplicate_code','wrong_macro','archived_category'])
def test_invalid_mixed_order_rolls_back_and_retains_input(operations,bad):
    db,c,s,item,cat,macro,rows=rows_for(operations)
    rows=[rows[3],rows[2]];extras={}
    if bad=='missing_category':rows[1]['line_new_category']=''
    if bad=='invalid_unit':rows[1]['line_unit']='invalid'
    if bad=='invalid_site':extras={'order_kind':'closed','site_id':'999999'}
    if bad=='duplicate_code':rows[1]['codice']='OIL'
    if bad=='wrong_macro':rows[1]['line_new_category']='Oli'
    if bad=='archived_category':
        cat.attiva=False;db.commit();rows[1].update(line_category_mode='existing',line_category_id=cat.id)
    result=c.post('/manager/ordini/nuovo',data=payload(operations,s,rows,**extras))
    assert result.status_code==200 and 'role="alert"' in result.text
    assert 'Lubrificanti' in result.text and 'OIL' in result.text and 'Catena' in result.text
    assert db.query(PurchaseOrder).count()==0
    assert db.query(MagazzinoItem).count()==1
    assert db.query(MagazzinoMacro).filter_by(name='Lubrificanti').count()==0
    assert db.query(MagazzinoCategoria).filter_by(nome='Oli').count()==0


def test_sites_only_active_and_invalid_arrays_rejected(operations):
    db,c,s,item,cat,macro,rows=rows_for(operations)
    archived=Site(name='Cantiere archiviato QA',is_active=False);db.add(archived);db.commit()
    page=c.get('/manager/ordini/nuovo');assert page.status_code==200
    assert 'Cantiere assegnato' in page.text and 'Cantiere riservato' in page.text
    assert 'Cantiere archiviato QA' not in page.text
    data=payload(operations,s,rows);data['line_unit']=['pz']
    assert 'Righe ordine incomplete' in c.post('/manager/ordini/nuovo',data=data).text
    assert db.query(PurchaseOrder).count()==0
    result=c.post('/manager/ordini/nuovo',data=payload(operations,s,[rows[0]],order_kind='closed',site_id=str(archived.id)))
    assert result.status_code==200 and 'cantiere valido' in result.text
    operations['actor'][0]=operations['capo']
    assert c.post('/manager/ordini/nuovo',data=payload(operations,s,rows)).status_code==403
