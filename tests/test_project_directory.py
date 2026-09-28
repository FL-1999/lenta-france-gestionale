import pytest
from models import ProjectPartner, ProjectPartnerSite, SiteStatusEnum
from services.project_directory import serialize
from routes.site_costs import token
from test_operations import operations


def setup(o):
    o['actor'][0] = o['manager']
    return dict(name='Bâtisseurs Côte d’Azur', categories=['moe', 'gros_oeuvre'], contact_name='Camille',
                email='contact@example.com', city='Nice', notes='Partenaire chantier',
                projects=[dict(site_id=o['site'].id, roles=['moe', 'gros_oeuvre'])])


def save(o, body):
    return o['client'].post('/manager/rubrica', json=body, headers={'x-csrf-token': token(o['manager'])})


def test_directory_links_detail_filters_and_site_reverse_link(operations):
    o=operations; b=setup(o); r=save(o,b); assert r.status_code==200,r.text
    pid=r.json()['id']; c=o['client']
    for path in ['/manager/rubrica','/manager/rubrica/nuovo',f'/manager/rubrica/{pid}',f'/manager/rubrica/{pid}/modifica']:
        response=c.get(path); assert response.status_code==200,response.text
    response=c.get('/manager/rubrica?q=camille&category=moe')
    assert response.context['total']==1
    assert c.get('/manager/rubrica?category=terrassement').context['total']==0
    response=c.get(f'/manager/cantieri/{o["site"].id}')
    assert response.status_code==200,response.text
    assert f'/manager/rubrica/{pid}' in response.text
    # Current project names and statuses are resolved from the site, not stale snapshots.
    site=o['site'];site.name='Nouveau nom';site.status=SiteStatusEnum.chiuso;o['db'].commit()
    response=c.get(f'/manager/rubrica/{pid}')
    assert 'Nouveau nom' in response.text and 'Terminato' in response.text
    assert response.context['record']['projects'][0]['roles']==['moe','gros_oeuvre']


def test_edit_archiving_stale_revisions_and_duplicate_names(operations):
    o=operations;b=setup(o);r=save(o,b);assert r.status_code==200
    duplicate={**b,'name':'  BÂTISSEURS CÔTE D’AZUR  '};assert save(o,duplicate).status_code==409
    b.update(r.json(),active=False,projects=[dict(site_id=o['other'].id,roles=['terrassement'])])
    r=save(o,b);assert r.status_code==200,r.text
    assert save(o,b).status_code==409
    assert o['client'].get('/manager/rubrica').context['total']==0
    assert o['client'].get('/manager/rubrica?archived=true').context['total']==1
    row=o['db'].query(ProjectPartner).one();assert len(row.projects)==1 and row.projects[0].site_id==o['other'].id
    b.update(r.json(),active=True);assert save(o,b).status_code==200
    assert o['client'].get('/manager/rubrica').context['total']==1


@pytest.mark.parametrize('change',[{'name':'  '},{'categories':[]},{'categories':['bad']},{'email':'bad@'},
    {'projects':[{'site_id':999999,'roles':['moe']}]},
    {'projects':[{'site_id':1,'roles':[]}]}, {'notes':'x'*4001}])
def test_invalid_directory_data_does_not_write(operations,change):
    o=operations;b=setup(o);b.update(change)
    assert save(o,b).status_code==400
    assert o['db'].query(ProjectPartner).count()==0


def test_duplicate_project_roles_one_row_and_permissions(operations):
    o=operations;b=setup(o);b['projects']*=2
    assert save(o,b).status_code==400
    b['projects']=b['projects'][:1]
    assert o['client'].post('/manager/rubrica',json=b).status_code==403
    assert o['client'].post('/manager/rubrica',json=b,headers={'x-csrf-token':token(o['manager']),'origin':'https://other.example'}).status_code==403
    o['actor'][0]=o['capo']
    assert o['client'].get('/manager/rubrica').status_code==403
    assert save(o,b).status_code==403


def test_site_deletion_keeps_directory_history_and_edit_preserves_it(operations):
    from services.site_deletion import delete_site_records
    o=operations;b=setup(o);r=save(o,b);assert r.status_code==200
    db=o['db'];site=o['site'];site.name='Nom conservé';site.code='REF-26';db.commit()
    delete_site_records(db,site);db.commit();db.expire_all()
    row=db.query(ProjectPartner).one();data=serialize(row)
    assert data['projects'][0]['site_id'] is None and data['projects'][0]['name']=='Nom conservé'
    b.update(r.json(),projects=[],phone='0102030405');assert save(o,b).status_code==200
    db.expire_all();assert db.query(ProjectPartnerSite).count()==1
    response=o['client'].get(f'/manager/rubrica/{row.id}')
    assert response.status_code==200 and 'REF-26' in response.text


def test_directory_escapes_contact_text_and_paginates(operations):
    o=operations;b=setup(o);b.update(name='<script>alert(1)</script>')
    r=save(o,b);assert r.status_code==200
    response=o['client'].get(f'/manager/rubrica/{r.json()["id"]}')
    assert '<script>alert(1)</script>' not in response.text and '&lt;script&gt;' in response.text
    for n in range(31):
        o['db'].add(ProjectPartner(name=f'Contact {n}',name_key=f'contact {n}',payload={'name':f'Contact {n}','categories':['other']},active=True))
    o['db'].commit()
    response=o['client'].get('/manager/rubrica?page=2')
    assert response.context['total']==32 and len(response.context['rows'])==2
