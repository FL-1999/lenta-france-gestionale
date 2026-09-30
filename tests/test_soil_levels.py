import json
import re
import pytest
from models import Fiche, SiteCoupe
from test_operations import operations
from test_site_pours import setup
from services.soil_levels import rebase_soil


def test_partial_fiche_update_preserves_start_snapshot_and_curve(operations):
    o = operations
    setup(o, ('P1', 'P2'))
    db, client = o['db'], o['client']
    coupe = db.query(SiteCoupe).one()
    coupe.quota_tn = 14.5
    coupe.quota_testa = coupe.quota_partenza_scavo = 13.5
    coupe.quota_fondo_teorica = 2.8
    coupe.scavo_da_tn = False
    coupe.profondita_teorica = 10.7
    coupe.terreno_teorico = '0-1 m: Remblais\n1-10.7 m: Sable'
    db.commit()
    data = dict(cantiere_id=o['site'].id, numero_pannello=1, data_scavo='2026-09-30',
                operatore='Squadra', tipologia_scavo='paratia', profondita_totale='2',
                strato_da=['0', '1'], strato_a=['1', '2'], strato_materiale=['riporto', 'sabbia'],
                quota_partenza='13.5', scavo_da_tn='0', quota_ngf_fondo='11.5')
    response = client.post('/manager/fiches/nuova', data=data, follow_redirects=False)
    assert response.status_code == 303, re.findall(r'<div[^>]*role="alert"[^>]*>(.*?)</div>',response.text,re.S)
    db.expire_all()
    item = db.query(Fiche).one()
    assert item.quota_partenza == 13.5 and item.quota_ngf_fondo == 11.5
    item.courbe_beton_active = True
    item.courbe_beton_realisee = json.dumps([{'volume': 1, 'hauteur': 2}])
    coupe.quota_partenza_scavo = 99
    db.commit()
    edit = client.get(f'/manager/fiches/{item.id}/modifica')
    assert edit.status_code == 200
    assert 'data-partenza="13.5"' in edit.text and 'data-partenza="99' not in edit.text
    data.update(profondita_totale='3', strato_a=['1', '3'], quota_ngf_fondo='10.5', larghezza_pannello='5', altezza_pannello='.5', coupe_id=coupe.id)
    response = client.post(f'/manager/fiches/{item.id}/modifica', data=data, follow_redirects=False)
    assert response.status_code == 303, re.findall(r'<div[^>]*role="alert"[^>]*>(.*?)</div>',response.text,re.S)
    db.expire_all()
    assert item.profondita_totale == 3 and item.quota_partenza == 13.5
    assert item.quota_ngf_fondo == 10.5 and item.courbe_beton_active
    assert json.loads(item.courbe_beton_realisee)[0]['volume'] == 1
    detail = client.get(f'/manager/fiches/{item.id}').text
    assert '13.50 → 12.50' in detail and '12.50 → 10.50' in detail
    data['quota_ngf_fondo'] = '9'
    response = client.post(f'/manager/fiches/{item.id}/modifica', data=data)
    assert response.status_code == 400 and 'id="quota_partenza"' in response.text
    db.expire_all()
    assert item.quota_ngf_fondo == 10.5


def test_rebase_soil_preserves_levels_and_clips_removed_ground():
    assert rebase_soil('0-1 m: Remblais\n1-5 m: Sable', 14.5, 13.5) == '0-4 m: Sable'
    assert rebase_soil('0-2 m: Sable', 0, -1) == '0-1 m: Sable'
    assert rebase_soil('0-2 m: Sable', -1, 0) == '1-3 m: Sable'
    assert rebase_soil('Note géologique', 14.5, 13.5) == 'Note géologique'
