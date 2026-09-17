import json
from datetime import date
from io import BytesIO

import pytest
import pypdfium2 as pdfium
from models import SitePlan, Fiche, FicheTypeEnum, SiteProgressGridName
from services.site_plan_import import import_pdf
from test_operations import operations


def vector_pdf(transform=None):
    # Small real vector PDF: no private project drawing in repository fixtures.
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream=b'0 0 0 RG 50 100 140 22 re S BT /F1 12 Tf 100 105 Td (P7a) Tj ET BT /F1 12 Tf 100 150 Td (2,9) Tj ET'
    if transform: stream=b'q '+transform.encode()+b' cm '+stream+b' Q'
    objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    data=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for pos in offsets[1:]: data+=f'{pos:010d} 00000 n \n'.encode()
    data+=f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return bytes(data)


def test_actual_vector_extraction_not_predefined_coordinates():
    layout,preview=import_pdf(vector_pdf())
    assert len(layout['panels'])==1
    p=layout['panels'][0]
    assert p['label']=='P7a' and p['width_m']==2.9
    assert not p['reviewed'] and p['element'] is None
    assert preview.startswith(b'\x89PNG')
    with pytest.raises(ValueError): import_pdf(vector_pdf(),2)
    with pytest.raises(ValueError): import_pdf(b'not-pdf')


@pytest.mark.parametrize('transform',['0 1 -1 0 270 0','.707 .707 -.707 .707 140 0'])
def test_rotated_labels_dimensions_and_geometry(transform):
    layout,_=import_pdf(vector_pdf(transform))
    assert len(layout['panels'])==1
    p=layout['panels'][0]
    assert p['label']=='P7a' and p['width_m']==2.9
    assert all(0<=x<=300 and 0<=y<=300 for x,y in p['points'])


def setup(o):
    o['actor'][0]=o['manager'];o['site'].numero_totale_paratie=2;o['db'].commit()
    c=o['client'];url=f'/manager/cantieri/{o["site"].id}/pianta'
    response=c.post(url+'/importa',files={'file':('drawing.pdf',vector_pdf(),'application/pdf')})
    assert response.status_code==200,response.text
    pid=response.json()['id'];data=c.get(url+f'/data?plan_id={pid}&draft=true').json()
    return c,url,pid,data['plan']


def payload(plan, **changes):
    panels=json.loads(json.dumps(plan['layout']['panels']))
    for p in panels:p.update(reviewed=True,element=1)
    return {'revision':plan['revision'],'panels':panels,'confirm':True,**changes}


def test_draft_approval_freeze_original_and_live_fiche_data(operations):
    o=operations;c,url,pid,plan=setup(o)
    assert c.get(url).status_code==200
    assert c.get(plan['original_url']).content==vector_pdf()
    assert c.get(plan['preview_url']).headers['content-type']=='image/png'
    body=payload(plan)
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    body['revision']+=1;body['panels'][0]['label']='P7A-modificato'
    assert c.put(url+f'/{pid}/bozza',json=body).status_code==200
    assert c.get(url+'/data').json()['plan']['layout']['panels'][0]['label']=='P7a'
    assert c.get(url+f'/data?plan_id={pid}&draft=true').json()['plan']['layout']['panels'][0]['label']=='P7A-modificato'
    assert c.put(url+f'/{pid}/bozza',json=body).status_code==409
    fiche=Fiche(date=date.today(),site_id=o['site'].id,created_by_id=o['manager'].id,
        numero_pannello=1,tipologia_scavo='paratia',fiche_type=list(FicheTypeEnum)[0],description='Test',
        metri_cubi_gettati=52,data_getto=date.today(),profondita_totale=17)
    o['db'].add(fiche);o['db'].commit()
    live=c.get(url+'/data').json()['elements'][0]
    assert live['concrete_m3']==52 and live['status']=='cast'
    fiche.metri_cubi_gettati=53;o['db'].commit()
    assert c.get(url+'/data').json()['elements'][0]['concrete_m3']==53
    assert c.get(plan['original_url']).content==vector_pdf()


def test_permissions_site_scope_and_unapproved_drawings(operations):
    o=operations;c,url,pid,plan=setup(o)
    o['actor'][0]=o['outsider']
    for path in ['', '/data',f'/{pid}/originale',f'/{pid}/anteprima']:
        assert c.get(url+path).status_code==403
    o['actor'][0]=o['capo']
    assert c.get(url+'/data').json()['plan'] is None
    assert c.get(url+f'/{pid}/originale').status_code==404
    assert c.put(url+f'/{pid}/bozza',json=payload(plan)).status_code==403
    assert c.post(url+'/importa',files={'file':('drawing.pdf',vector_pdf())}).status_code==403
    o['actor'][0]=o['manager']
    assert c.put(url+f'/{pid}/convalida',json=payload(plan)).status_code==200
    o['actor'][0]=o['capo']
    assert c.get(url+'/data?draft=true').json()['plan']['editing'] is False
    assert c.get(url+f'/{pid}/originale').status_code==200
    other=f'/manager/cantieri/{o["other"].id}/pianta/{pid}/originale'
    o['actor'][0]=o['manager'];assert c.get(other).status_code==404


@pytest.mark.parametrize('change', ['unchecked','no_width','outside','crossed','bad_link','duplicate_link','no_confirmation'])
def test_validation_leaves_approved_snapshot_untouched(operations,change):
    o=operations;c,url,pid,plan=setup(o);body=payload(plan)
    if change=='unchecked':body['panels'][0]['reviewed']=False
    if change=='no_width':body['panels'][0]['width_m']=None
    if change=='outside':body['panels'][0]['points'][0]=[-1,3]
    if change=='crossed':body['panels'][0]['points']=[[10,10],[50,50],[10,50],[50,10]]
    if change=='bad_link':body['panels'][0]['element']=999
    if change=='duplicate_link':body['panels'].append({**body['panels'][0],'key':'another'})
    if change=='no_confirmation':body['confirm']=False
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==400
    o['db'].expire_all();row=o['db'].get(SitePlan,pid)
    assert row.approved is None and row.revision==1


def test_repeated_names_are_valid_but_links_are_distinct_and_new_pdf_is_only_draft(operations):
    c,url,pid,plan=setup(operations);body=payload(plan)
    body['panels'].append({**body['panels'][0],'key':'second-panel','element':2})
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    newer=c.post(url+'/importa',files={'file':('revision.pdf',vector_pdf())}).json()['id']
    assert newer!=pid
    assert c.get(url+'/data').json()['plan']['id']==pid
    assert c.get(url+f'/data?plan_id={newer}&draft=true').json()['plan']['editing']


def test_automatic_link_only_unique_custom_name_and_no_mutation_of_fiches(operations):
    o=operations;o['db'].add(SiteProgressGridName(site_id=o['site'].id,tipologia_scavo='paratia',numero_elemento=1,nome_personalizzato='P7a'));o['db'].commit()
    c,url,pid,plan=setup(o)
    assert plan['layout']['panels'][0]['element']==1
    assert o['db'].query(Fiche).count()==0
    assert c.post(url+'/importa',files={'file':('bad.pdf',b'invalid')}).status_code==400
    assert c.put(url+f'/{pid}/bozza',json=payload(plan),headers={'Origin':'https://other.example'}).status_code==403


def test_unlinked_panels_can_be_approved_without_fabricating_progress(operations):
    c,url,pid,plan=setup(operations);body=payload(plan);body['panels'][0]['element']=None
    assert c.put(url+f'/{pid}/convalida',json=body).status_code==200
    assert c.get(url+'/data').json()['plan']['layout']['panels'][0]['element'] == 1
    assert operations['db'].query(Fiche).count() == 0
    assert c.get(url+'/data').json()['elements'][0]['status'] == 'planned'
