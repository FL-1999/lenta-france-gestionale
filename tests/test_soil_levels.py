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


@pytest.mark.parametrize('reference, theory, expected', [
    ('tn', '0-1 m: Remblais\n1-11.7 m: Sable', '0-10.7 m: Sable'),
    ('tn', '0-2 m: Remblais\n2-11.7 m: Sable', '0-1 m: Remblais\n1-10.7 m: Sable'),
    ('scavo', '0-1 m: Remblais\n1-10.7 m: Sable', '0-1 m: Remblais\n1-10.7 m: Sable'),
    (None, '0-1 m: Remblais\n1-10.7 m: Sable', '0-1 m: Remblais\n1-10.7 m: Sable'),
    ('tn', '0-1 m: Remblais', ''),
])
def test_independent_theory_origin_and_frozen_fiche(operations, reference, theory, expected):
    o = operations; setup(o, ('P1', 'P2')); db = o['db']; client = o['client']
    coupe = db.query(SiteCoupe).one()
    coupe.quota_tn = 14.5; coupe.quota_partenza_scavo = coupe.quota_testa = 13.5
    coupe.scavo_da_tn = False; coupe.quota_fondo_teorica = 2.8; coupe.profondita_teorica = 10.7
    coupe.terreno_riferimento = reference; coupe.terreno_teorico = theory; db.commit()
    data = dict(cantiere_id=o['site'].id, numero_pannello=1, data_scavo='2026-09-30',
                operatore='Squadra', tipologia_scavo='paratia', profondita_totale='2',
                strato_da=['0'], strato_a=['2'], strato_materiale=['sabbia'],
                quota_partenza='13.5', scavo_da_tn='0', quota_ngf_fondo='11.5')
    response = client.post('/manager/fiches/nuova', data=data, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all(); item = db.query(Fiche).one()
    assert item.terreno_teorico == expected
    assert json.loads(item.coupe_snapshot)['terreno_riferimento'] == reference
    assert coupe.terreno_teorico == theory  # Full theoretical log remains intact.
    if not expected:
        assert 'Remblais' not in client.get(f'/manager/fiches/{item.id}').text
    coupe.quota_tn = 99; coupe.terreno_teorico = '0-100 m: Argile'; db.commit()
    data.update(coupe_id=coupe.id, profondita_totale='3', strato_a=['3'], quota_ngf_fondo='10.5',
                larghezza_pannello='5', altezza_pannello='.5')
    assert client.post(f'/manager/fiches/{item.id}/modifica', data=data, follow_redirects=False).status_code == 303
    db.expire_all(); assert item.terreno_teorico == expected


def test_theoretical_reference_form_validation_and_persistence(operations):
    o = operations; o['actor'][0] = o['manager']; client = o['client']
    url = f'/manager/cantieri/{o["site"].id}/configurazione-progetto'
    data = dict(coupe_nome='Coupe TN', coupe_quota_tn='14.5', coupe_scavo_da_tn='0',
                coupe_quota_partenza_scavo='13.5', coupe_quota_fondo_teorica='2.8',
                coupe_terreno_riferimento='tn', coupe_terreno_teorico='0-1 m: Remblais\n1-11.7 m: Sable')
    assert client.post(url, data=data, follow_redirects=False).status_code == 303
    o['db'].expire_all(); coupe = o['db'].query(SiteCoupe).one()
    assert coupe.terreno_riferimento == 'tn' and coupe.profondita_teorica == pytest.approx(10.7)
    data['coupe_id'] = str(coupe.id); data['coupe_quota_tn'] = ''
    response = client.post(url, data=data)
    assert response.status_code == 400 and 'Completa la quota del riferimento' in response.text
    data['coupe_quota_tn'] = '14.5'; data['coupe_terreno_riferimento'] = 'other'
    assert client.post(url, data=data).status_code == 400
    o['db'].expire_all(); assert coupe.terreno_riferimento == 'tn'



def test_full_frozen_theory_is_available_when_start_is_corrected_upward():
    from types import SimpleNamespace
    from services.soil_levels import fiche_theory_source
    coupe = SimpleNamespace(terreno_riferimento='tn', quota_tn=14.5, scavo_da_tn=False,
                            terreno_teorico='0-1 m: Remblais\n1-11.7 m: Sable')
    item = SimpleNamespace(coupe_snapshot='saved', report_coupe=coupe,
                           quota_partenza=13.5, terreno_teorico='0-10.7 m: Sable')
    text, origin = fiche_theory_source(item)
    assert rebase_soil(text, origin, 14.5) == coupe.terreno_teorico
    item.terreno_teorico = '0-10.7 m: Argile'
    assert fiche_theory_source(item) == (item.terreno_teorico, 13.5)


def test_soil_reference_upgrade_is_idempotent_and_keeps_old_origin(operations):
    from sqlalchemy import text
    from database import ensure_model_columns
    from models import Base
    from services.soil_levels import theoretical_origin
    o = operations; setup(o, ('P1',)); db = o['db']
    coupe = db.query(SiteCoupe).one()
    coupe.scavo_da_tn = False; coupe.quota_tn = 14.5; coupe.quota_partenza_scavo = 13.5
    coupe.terreno_teorico = '0-1 m: Remblais'; db.commit()
    engine = db.get_bind()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE site_coupes DROP COLUMN terreno_riferimento'))
    for _ in range(2): ensure_model_columns(engine, (Base.metadata,))
    db.expire_all()
    assert coupe.terreno_riferimento is None
    assert theoretical_origin(coupe) == 13.5
    assert coupe.terreno_teorico == '0-1 m: Remblais'
