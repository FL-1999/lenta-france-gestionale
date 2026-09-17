from test_operations import operations
from test_purchasing_workflows import setup, order
from models import User, RoleEnum


def test_purchase_navigation_roles_and_fallback_parents(operations):
    db,c,s,item,cat=setup(operations)
    response=order(operations,s,item,cat)
    order_path=response.headers['location']
    for path,section in [('/manager/magazzino','items'),('/manager/ordini','orders'),
        ('/manager/fornitori','suppliers'),('/manager/magazzino/movimenti','movements'),
        ('/manager/magazzino/richieste','requests'),('/manager/magazzino/categorie','categories')]:
        r=c.get(path); assert r.status_code==200
        assert r.context['purchase_nav']['section']==section
        assert 'data-purchase-context' in r.text
        assert 'nav class="warehouse-toolbar"' not in r.text
        assert 'magazzino-pill-bar' not in r.text
        assert 'data-purchase-section="suppliers"' in r.text
    details=c.get(order_path)
    assert details.context['purchase_nav']['parent']=='/manager/ordini'
    form=c.get(order_path+'/bolle/nuova')
    assert form.context['purchase_nav']['parent']==order_path.replace('http://testserver','')
    edit=c.get(f'/manager/magazzino/{item.id}/modifica')
    assert edit.context['purchase_nav']['parent']==f'/manager/magazzino/items/{item.id}/scheda'
    result=c.post(f'/manager/magazzino/{item.id}/modifica',data={'nome':item.nome,'codice':item.codice,'attivo':'on'},follow_redirects=False)
    assert result.status_code==303 and result.headers['location'].endswith(f'/items/{item.id}/scheda')
    warehouse=User(email='warehouse-nav@example.com',role=RoleEnum.magazzino,hashed_password='x',is_active=True)
    db.add(warehouse);db.commit();operations['actor'][0]=warehouse
    r=c.get('/manager/magazzino');assert r.status_code==200
    assert 'data-purchase-section="items"' in r.text
    assert 'data-purchase-section="orders"' not in r.text
    assert 'data-purchase-section="suppliers"' not in r.text
    assert c.get('/manager/ordini').status_code==403
    operations['actor'][0]=operations['capo']
    r=c.get('/capo/dashboard');assert r.status_code==200
    assert 'data-purchase-section="suppliers"' not in r.text
    assert '/capo/magazzino' in r.text
