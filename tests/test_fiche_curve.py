from math import pi
from types import SimpleNamespace

import pytest
from main import _apply_courbe_beton_fields, _build_courbe_beton_payload
from services.fiche_curve import curve_defaults
from test_operations import operations
from test_fiche_consumption import make_fiche
from utils.production_stats import compute_fiche_volumes


def test_inverted_depths_are_flagged_without_rewriting_measurements():
    import json
    from services.fiche_curve import curve_depth_increases, compact_courbe_svg
    from xml.etree import ElementTree as ET
    raw=[{'volume':v,'hauteur':d} for v,d in [(0,0),(2.5,2),(10,5),(17.5,7),(25,9),(32.5,11)]]
    f=SimpleNamespace(tipologia_scavo='paratia',profondita_totale=11,larghezza_pannello=6.3,
                      altezza_pannello=.42,courbe_beton_realisee=json.dumps(raw))
    original=f.courbe_beton_realisee
    payload=_build_courbe_beton_payload(f)
    assert payload['depth_increases'] and payload['realisee']==raw
    assert f.courbe_beton_realisee==original
    corrected=[{'volume':v,'hauteur':d} for v,d in [(32.5,0),(25,2),(17.5,5),(10,7),(2.5,9),(0,11)]]
    assert not curve_depth_increases(corrected)
    f.courbe_beton_realisee=json.dumps(corrected)
    payload=_build_courbe_beton_payload(f)
    svg=ET.fromstring(compact_courbe_svg(payload,13.8))
    lines=svg.findall('{http://www.w3.org/2000/svg}polyline')
    assert len(lines)==2
    for line in lines:
        coords=[tuple(map(float,p.split(','))) for p in line.attrib['points'].split()]
        assert coords[0][0]<coords[-1][0] and coords[0][1]>coords[-1][1]
    texts=[e.text for e in svg.findall('{http://www.w3.org/2000/svg}text')]
    assert '13.80' in texts and '2.80' in texts


def test_large_curve_tick_labels_match_the_plotted_scale():
    from main import _courbe_svg
    from xml.etree import ElementTree as ET
    svg=ET.fromstring(_courbe_svg({'realisee':[{'volume':0,'hauteur':10},{'volume':20,'hauteur':0}]}))
    texts=[e.text for e in svg.findall('{http://www.w3.org/2000/svg}text')]
    assert '10.8' in texts and '21.6' in texts
    assert 'Profondeur restante (m)' in texts


def test_defaults_use_geometry_and_do_not_invent_measured_points():
    f=SimpleNamespace(tipologia_scavo='paratia',profondita_totale=10.7,
                      larghezza_pannello=6.3,altezza_pannello=.42)
    assert curve_defaults(f)=={'volume':28.31,'start':10.7,'end':0}
    payload=_build_courbe_beton_payload(f)
    assert payload['theorique']==[{'volume':0,'hauteur':10.7},{'volume':28.31,'hauteur':0}]
    assert payload['realisee']==payload['tube']==[]
    f.tipologia_scavo='palo';f.diametro_palo=1.2
    assert curve_defaults(f)['volume']==round(pi*.6**2*10.7,2)
    f.profondita_totale=None;f.quota_partenza=13.5;f.quota_ngf_fondo=2.8
    assert curve_defaults(f)['start']==pytest.approx(10.7)
    f.quota_ngf_fondo=None
    assert curve_defaults(f)['volume'] is None and curve_defaults(f)['start'] is None


def test_curve_save_fills_blanks_keeps_overrides_and_actual_consumption(operations):
    o=operations; o['actor'][0]=o['manager'];db=o['db'];c=o['client']
    f=make_fiche(o,actual=25)
    payload={'quota_tn':'16','quota_testa_getto':'15','larghezza_pannello':'2',
             'altezza_pannello':'1','profondita_totale':'10','courbe_beton_active':'1'}
    url=f'/manager/fiches/{f.id}/dati-pdf'
    assert c.post(url,data=payload,follow_redirects=False).status_code==303
    db.refresh(f)
    assert f.courbe_beton_volume_total==20 and f.courbe_beton_hauteur_initiale==10 and f.courbe_beton_hauteur_finale==0
    assert f.courbe_beton_realisee is None and f.metri_cubi_gettati==25
    assert compute_fiche_volumes(f)['volume_cls_reale']==25
    assert compute_fiche_volumes(f)['delta_cls_pct']==25
    payload.update(courbe_beton_volume_total='22,5',courbe_beton_hauteur_initiale='11',
                   courbe_realisee_volume=['0','25'],courbe_realisee_hauteur=['11','0'])
    assert c.post(url,data=payload,follow_redirects=False).status_code==303
    db.refresh(f)
    assert f.courbe_beton_volume_total==22.5 and f.courbe_beton_hauteur_initiale==11
    assert len(_build_courbe_beton_payload(f)['realisee'])==2
    payload['courbe_realisee_hauteur']=['11','']
    assert c.post(url,data=payload,follow_redirects=False).status_code==400
    db.refresh(f);assert len(_build_courbe_beton_payload(f)['realisee'])==2
    payload.update(courbe_beton_active='0')
    assert c.post(url,data=payload,follow_redirects=False).status_code==303
    db.refresh(f);assert not f.courbe_beton_active


def test_legacy_empty_curve_renders_without_mutating_the_fiche(operations):
    f=make_fiche(operations,actual=0)
    f.courbe_beton_active=True;operations['db'].commit()
    payload=_build_courbe_beton_payload(f)
    assert len(payload['theorique'])==2 and payload['realisee']==[]
    assert f.courbe_beton_volume_total is None
    assert compute_fiche_volumes(f)['volume_cls_reale']==0


def test_blank_fields_are_derived_when_submitted_without_javascript():
    f=SimpleNamespace(tipologia_scavo='paratia',profondita_totale=10,larghezza_pannello=2,altezza_pannello=.5)
    _apply_courbe_beton_fields(f,courbe_beton_active=True,courbe_realisee_volume=[],courbe_realisee_hauteur=[])
    assert f.courbe_beton_volume_total==10 and f.courbe_beton_hauteur_initiale==10
