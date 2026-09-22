import json
import re
import pytest
from jinja2 import Environment, DictLoader, select_autoescape
from starlette.requests import Request
from ui_i18n import InterfaceTranslation
from test_operations import operations
from models import SiteCoupe, SiteProgressGridName


def test_literal_translation_keeps_user_data_and_escapes_attributes():
    env=Environment(loader=DictLoader({'page.html':'<label>Nome</label><input placeholder="Cerca"><p>{{ name }}</p><p>{{ "Nuova coupe" if new else "Modifica" }}</p><span title="📍 Mappa cantiere">Cantiere</span>'}),autoescape=True,extensions=[InterfaceTranslation])
    request=Request({'type':'http','headers':[(b'cookie',b'lang=fr')]})
    text=env.get_template('page.html').render(request=request,name='Cantiere <script>',new=True)
    assert '<label>Nom</label>' in text and 'placeholder="Rechercher"' in text
    assert 'Nouvelle coupe' in text and 'Cantiere &lt;script&gt;' in text
    assert 'Carte du chantier' in text


def test_invalid_coupe_preserves_every_row_and_equipment(operations):
    o=operations;o['actor'][0]=o['manager'];c=o['client'];db=o['db']
    route=f'/manager/cantieri/{o["site"].id}/configurazione-progetto'
    data={'coupe_id':['',''],'coupe_nome':['Test géologie','Seconde coupe'],
          'coupe_quota_tn':['10','20'],'coupe_quota_fondo_teorica':['-5',''],
          'coupe_profondita_teorica':['8',''],'coupe_scavo_da_tn':['1','0'],
          'coupe_paratie':['1,3','2'],'coupe_armatura':['Cage A','Cage B'],
          'coupe_terreno_teorico':['0-2 m: Sable\n2-8 m: Argile',''],
          'coupe_note':['Ne pas perdre mes notes','Deuxième note'],
          'equipment_tipologia':['paratia'],'equipment_numero':['1'],'equipment_mode':['sonic']}
    response=c.post(route,data=data,cookies={'lang':'fr'})
    assert response.status_code==400
    assert 'Cotes incohérentes' in response.text and '15 m' in response.text
    for value in ['Test géologie','Seconde coupe','Cage A','Cage B','Ne pas perdre mes notes','Deuxième note','2-8 m: Argile','value="1,3"']:
        assert value in response.text
    assert 'Panneaux de cette coupe' in response.text and 'Terrain théorique' in response.text
    assert db.query(SiteCoupe).count()==0
    data['coupe_profondita_teorica']=['15','']
    assert c.post(route,data=data,follow_redirects=False).status_code==303
    assert db.query(SiteCoupe).count()==2


def test_panel_picker_includes_named_elements_and_natural_order(operations):
    o=operations;o['actor'][0]=o['manager'];db=o['db']
    o['site'].numero_totale_paratie=0
    for n,label in [(15,'P10'),(40,'P2'),(81,'P7B'),(63,'P7A')]:
        db.add(SiteProgressGridName(site_id=o['site'].id,tipologia_scavo='paratia',numero_elemento=n,nome_personalizzato=label))
    db.commit()
    data=o['client'].get(f'/manager/cantieri/{o["site"].id}/pianta/data').json()
    assert [e['label'] for e in data['elements']]==['P2','P7A','P7B','P10']
    assert [e['number'] for e in data['elements']]==[40,63,81,15]


def test_soil_inconsistency_reports_layer_without_writing(operations):
    o=operations;o['actor'][0]=o['manager']
    response=o['client'].post(f'/manager/cantieri/{o["site"].id}/configurazione-progetto',data={'coupe_nome':'Coupe sol','coupe_terreno_teorico':'0-2 m: Sable\n1-5 m: Argile'},cookies={'lang':'fr'})
    assert response.status_code==400 and 'Couche 2' in response.text
    assert '1-5 m: Argile' in response.text
    assert not o['db'].query(SiteCoupe).count()


@pytest.mark.parametrize('path,heading',[
    ('/manager/cantieri','Chantiers'),
    ('/manager/depositi','Dépôts'),
    ('/manager/fornitori','Fournisseurs'),
    ('/manager/ordini','Commandes'),
    ('/manager/magazzino','Articles'),
    ('/manager/fiches','Fiches'),
])
def test_french_section_headings(operations,path,heading):
    operations['actor'][0]=operations['manager']
    response=operations['client'].get(path,cookies={'lang':'fr'})
    assert response.status_code==200
    titles=re.findall(r'<h1\b[^>]*>(.*?)</h1>',response.text,re.S)
    assert any(heading in re.sub(r'<[^>]*>','',title) for title in titles),titles
