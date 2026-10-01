import json
import pytest
from models import SiteCoupe, SiteStrutLevel
from services.coupe_drawing import read_pdf, parse_lines, validate_info
from test_operations import operations


def section_pdf(two=False, scanned=False):
    # Synthetic vector fixture, never a customer's engineering drawing.
    lines=['Coupe 2 - Ht.=8.70m, Htot=10.70m Ep.=0.42m', 'TN +14.50 NGF',
           'Tete PM avant recepage +13.50 NGF', 'Axe du buton +12.00 NGF',
           'Terrassier +11.50 NGF', 'Base PM +4.80 NGF', 'Base PM +2.80 NGF',
           'Traitement permeabilite : +4.80 NGF / +3.30 NGF']
    stream=b''
    if not scanned:
        for i,line in enumerate(lines):
            stream+=f'BT /F1 10 Tf 20 {560-i*34} Td ({line}) Tj ET\n'.encode()
        if two:
            stream+=b'BT /F1 10 Tf 450 560 Td (Coupe 3) Tj ET\nBT /F1 10 Tf 450 526 Td (TN +99.00 NGF) Tj ET\n'
    stream+=b'0 0 1 RG 20 446 m 100 446 l S\n'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 600] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(data);data+=f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for pos in offsets[1:]:data+=f'{pos:010d} 00000 n \n'.encode()
    data+=f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return bytes(data)


def info(**changes):
    return json.dumps(dict(reviewed=True,struts=[8,12],treatment=dict(state='present',top=4.8,bottom=3.3),
                           source=dict(filename='Coupe.pdf',page=1),**changes))


def test_real_pdf_extracts_coupe_and_only_explicit_buton_axis():
    result=read_pdf(section_pdf())
    assert result['fields']==dict(nome='Coupe 2',quota_tn=14.5,quota_testa=13.5,spessore=.42,
        base_paroi_mecanique=4.8,quota_fondo_teorica=2.8,profondita_teorica=11.7)
    assert result['struts']==[12]
    assert result['treatment']==dict(state='present',top=4.8,bottom=3.3)
    assert result['preview'].startswith('iVBOR')
    assert result['dimensions']==dict(mechanical=8.7,total=10.7)


def test_multi_coupe_requires_crop_and_crop_excludes_other_values():
    assert read_pdf(section_pdf(two=True))['blocked']
    result=read_pdf(section_pdf(two=True),crop=[0,0,.5,1])
    assert not result['blocked'] and result['fields']['quota_tn']==14.5
    assert result['struts']==[12]


@pytest.mark.parametrize('kwargs',[dict(page_number=2),dict(crop=[0,0,2,1]),dict(crop=[0,0,0,1]),dict(crop='bad'),dict(crop=[0,0,float('nan'),1])])
def test_bad_page_or_region_is_rejected(kwargs):
    with pytest.raises(ValueError):read_pdf(section_pdf(),**kwargs)


def test_scans_and_ambiguous_elevations_do_not_invent_values():
    result=read_pdf(section_pdf(scanned=True))
    assert not result['fields'] and not result['struts']
    assert result['treatment']['state']=='unknown'
    result=parse_lines([dict(text=s) for s in ['Coupe 2 Ht.=8.70m Htot=10.70m',
        'TN +14.50 NGF', 'TN +15.00 NGF', 'Tete PM +13.50 NGF', 'Base PM +5.00 NGF',
        'Axe du buton +12.00 NGF / +11.50 NGF', 'Traitement permeabilite']])
    assert 'quota_tn' not in result['fields'] and 'base_paroi_mecanique' not in result['fields']
    assert result['struts']==[] and result['warnings']
    assert result['treatment']['state']=='present' and result['treatment']['top'] is None


def test_metadata_validation_orders_levels_without_inferring_counts():
    result=validate_info(info())
    assert result['struts']==[12,8]
    for update in [dict(reviewed=False),dict(struts=[12,12]),dict(struts=[None]),
                   dict(struts=[float('inf')]),dict(treatment=dict(state='present',top=2,bottom=3)),
                   dict(treatment=dict(state='present',top=None))]:
        data=json.loads(info());data.update(update)
        with pytest.raises(ValueError):validate_info(json.dumps(data))


def test_read_is_authorized_and_does_not_save_anything(operations):
    o=operations;c=o['client'];url=f'/manager/cantieri/{o["site"].id}/coupe/leggi-pdf'
    upload=dict(files={'file':('Coupe.pdf',section_pdf(),'application/pdf')},headers={'X-Coupe-Reader':'1'})
    assert c.post(url,**upload).status_code==403
    o['actor'][0]=o['manager']
    assert c.post(url,files=upload['files']).status_code==403
    assert c.post(url,**{**upload,'headers':{'X-Coupe-Reader':'1','Origin':'https://outside.example'}}).status_code==403
    response=c.post(url,**upload)
    assert response.status_code==200,response.text
    assert response.json()['struts']==[12]
    assert not o['db'].query(SiteCoupe).count()


def test_review_save_preserves_metadata_on_error_and_existing_production(operations):
    o=operations;o['actor'][0]=o['manager'];c=o['client'];db=o['db']
    level=SiteStrutLevel(site_id=o['site'].id,level_index=1,level_quota='+12 NGF',total_struts_level=8,done_struts_level=3)
    db.add(level);db.commit()
    url=f'/manager/cantieri/{o["site"].id}/configurazione-progetto'
    data=dict(coupe_nome='Coupe 2',coupe_drawing_info=info(),coupe_quota_tn='14.5',
              coupe_quota_testa='13.5',coupe_base_paroi_mecanique='4.8',coupe_quota_fondo_teorica='2.8',
              coupe_profondita_teorica='10.7',coupe_spessore='.42')
    bad=c.post(url,data=data)
    assert bad.status_code==400 and 'Coupe.pdf' in bad.text
    assert not db.query(SiteCoupe).count()
    data['coupe_profondita_teorica']='11.7'
    response=c.post(url,data=data,follow_redirects=False)
    assert response.status_code==303,response.text
    coupe=db.query(SiteCoupe).one()
    assert coupe.drawing_info['struts']==[12,8]
    db.refresh(level);assert level.total_struts_level==8 and level.done_struts_level==3
    response=c.get(f'/manager/cantieri/{o["site"].id}/avanzamento',cookies={'lang':'fr'})
    assert response.status_code==200 and 'Axe du buton' in response.text and '+12.00' in response.text
    data['coupe_id']=str(coupe.id);data.pop('coupe_drawing_info')
    assert c.post(url,data=data,follow_redirects=False).status_code==303
    db.refresh(coupe);assert coupe.drawing_info['struts']==[12,8]


def test_unreviewed_import_never_saved(operations):
    o=operations;o['actor'][0]=o['manager'];payload=json.loads(info());payload['reviewed']=False
    response=o['client'].post(f'/manager/cantieri/{o["site"].id}/configurazione-progetto',data=dict(coupe_nome='Coupe 2',coupe_drawing_info=json.dumps(payload)))
    assert response.status_code==400 and not o['db'].query(SiteCoupe).count()
