import re
from datetime import date, timedelta

import pytest

from test_operations import operations
from models import (MagazzinoItem, MagazzinoMovimento, MagazzinoRichiesta,
                    MagazzinoRichiestaStatusEnum as Status, MagazzinoRichiestaPrioritaEnum as Priority,
                    RoleEnum, AuditLog)


def seed(o):
    from database import ensure_model_columns, Base
    from sqlmodel import SQLModel
    ensure_model_columns(o['db'].get_bind(), (Base.metadata, SQLModel.metadata))
    o['actor'][0] = o['manager']
    items = [MagazzinoItem(nome='Acciaio', codice='AC-1', unita_misura='kg', quantita_disponibile=10, costo_unitario=2.5),
             MagazzinoItem(nome='Senza costo', codice='SC-1', quantita_disponibile=3, costo_unitario=None, soglia_minima=5),
             MagazzinoItem(nome='Gratuito', quantita_disponibile=0, costo_unitario=0, soglia_minima=2),
             MagazzinoItem(nome='Archiviato', attivo=False, quantita_disponibile=100, costo_unitario=100)]
    o['db'].add_all(items); o['db'].commit()
    return items


def form(o, item, **changes):
    page = o['client'].get('/manager/magazzino/prezzi')
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return dict(csrf=csrf, expected='' if item.costo_unitario is None else str(item.costo_unitario), cost='3,25', **changes)


def test_overview_counts_value_priorities_and_real_links(operations):
    o = operations; items = seed(o); db = o['db']
    normal = MagazzinoRichiesta(richiesto_da_user_id=o['capo'].id, cantiere_id=o['site'].id,
                                stato=Status.approvata, data_necessaria=date.today()-timedelta(days=1))
    urgent = MagazzinoRichiesta(richiesto_da_user_id=o['capo'].id, stato=Status.in_attesa, priorita=Priority.high)
    partial = MagazzinoRichiesta(richiesto_da_user_id=o['capo'].id, stato=Status.parziale)
    closed = MagazzinoRichiesta(richiesto_da_user_id=o['capo'].id, stato=Status.evasa)
    db.add_all([normal, urgent, partial, closed]); db.commit()
    o['manager'].role = RoleEnum.magazzino; db.commit()
    response = o['client'].get('/manager/magazzino/dashboard')
    assert response.status_code == 200
    ctx = response.context
    assert ctx['valuation'] == dict(total=3, priced=2, missing=1, value=25.0, missing_stock=1, coverage=67)
    assert ctx['low_count'] == 2 and ctx['empty_count'] == 1
    assert ctx['waiting_count'] == 1 and ctx['preparing_count'] == 2
    assert [r.id for r in ctx['request_queue']] == [urgent.id, normal.id, partial.id]
    for path in ['/manager/magazzino?view=all', '/manager/magazzino/richieste',
                 '/manager/trasporti', '/manager/depositi', '/manager/magazzino/movimenti', '/manager/magazzino/prezzi']:
        assert o['client'].get(path).status_code == 200, path
    preparing = o['client'].get('/manager/magazzino/richieste?stato=da_preparare')
    assert {r.id for r in preparing.context['richieste']} == {normal.id, partial.id}
    prices = o['client'].get('/manager/magazzino/prezzi?missing=true')
    assert [i.id for i in prices.context['items']] == [items[1].id]
    assert not prices.context['can_edit_prices']
    assert 'name="cost"' not in prices.text
    assert o['client'].get('/manager/ordini').status_code == 403


def test_update_cost_recalculates_without_changing_quantity_or_movements(operations):
    o = operations; item = seed(o)[0]
    response = o['client'].post(f'/manager/magazzino/items/{item.id}/prezzo', data=form(o, item), follow_redirects=False)
    assert response.status_code == 303
    o['db'].refresh(item)
    assert item.costo_unitario == 3.25 and item.quantita_disponibile == 10
    assert o['db'].query(MagazzinoMovimento).count() == 0
    assert o['db'].query(AuditLog).filter_by(action='WAREHOUSE_UNIT_COST_UPDATED').count() == 1
    assert o['client'].get('/manager/magazzino/dashboard').context['valuation']['value'] == 32.5
    body = form(o, item); body['cost'] = ''
    assert o['client'].post(f'/manager/magazzino/items/{item.id}/prezzo', data=body).status_code == 200
    assert o['client'].get('/manager/magazzino/dashboard').context['valuation']['missing'] == 2


@pytest.mark.parametrize('value', ['-1', 'NaN', 'Infinity', '1e309', '1e308', 'non valido'])
def test_invalid_cost_preserves_input_and_existing_stock(operations, value):
    o = operations; item = seed(o)[0]; body = form(o, item); body['cost'] = value
    response = o['client'].post(f'/manager/magazzino/items/{item.id}/prezzo', data=body)
    assert response.status_code == 400
    assert response.context['entered'] == value and 'aria-invalid="true"' in response.text
    o['db'].refresh(item)
    assert item.costo_unitario == 2.5 and item.quantita_disponibile == 10


def test_stale_cost_cannot_overwrite_and_csrf_is_required(operations):
    o = operations; item = seed(o)[0]; body = form(o, item)
    item.costo_unitario = 7; o['db'].commit()
    path = f'/manager/magazzino/items/{item.id}/prezzo'
    assert o['client'].post(path, data=body).status_code == 409
    o['db'].refresh(item); assert item.costo_unitario == 7
    body = form(o, item)
    assert o['client'].post(path, data=body, headers={'Origin': 'https://unrelated.invalid'}).status_code == 403
    body['csrf'] = 'bad'
    assert o['client'].post(path, data=body).status_code == 403


@pytest.mark.parametrize('role', [RoleEnum.magazzino, RoleEnum.caposquadra, RoleEnum.driver, RoleEnum.ferraiolo])
def test_roles_cannot_gain_price_editing_from_a_link(operations, role):
    o = operations; item = seed(o)[0]; body = form(o, item)
    o['manager'].role = role; o['db'].commit()
    assert o['client'].post(f'/manager/magazzino/items/{item.id}/prezzo', data=body).status_code == 403
    assert o['client'].get('/manager/magazzino/prezzi').status_code == (200 if role == RoleEnum.magazzino else 403)


def test_full_article_editor_also_rejects_negative_cost(operations):
    o = operations; item = seed(o)[0]
    response = o['client'].post(f'/manager/magazzino/{item.id}/modifica', data={
        'nome': item.nome, 'codice': item.codice, 'costo_unitario': '-3', 'attivo': 'on'})
    assert response.status_code == 400
    o['db'].refresh(item); assert item.costo_unitario == 2.5


def test_failed_missing_cost_form_remains_visible_after_concurrent_update(operations):
    o = operations; item = seed(o)[1]; body = form(o, item, missing='true')
    item.costo_unitario = 4; o['db'].commit()
    response = o['client'].post(f'/manager/magazzino/items/{item.id}/prezzo', data=body)
    assert response.status_code == 409
    assert any(row.id == item.id for row in response.context['items'])
    assert response.context['entered'] == '3,25'
    o['db'].refresh(item); assert item.costo_unitario == 4
