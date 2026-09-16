"""Regressions from production feedback: shared legacy schema and work week.

Also run on the dedicated PostgreSQL CI database via the operations fixture.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError
from sqlmodel import SQLModel, Session

import main
from database import ensure_model_columns, get_session
from models import Base, PersonalePresenza, VeicoloTrasporto
from models.veicoli import Veicolo
from personale_presenze_repository import copy_week_attendance_from_monday
from test_operations import operations


def test_both_vehicle_mappings_upgrade_existing_database_without_data_loss(operations):
    o = operations
    engine = o['db'].get_bind()
    assert 'anno' not in {c['name'] for c in inspect(engine).get_columns('veicoli')}
    vehicle = VeicoloTrasporto(marca='Camion', modello='Collaudo', targa='TEST-VEHICLE', visibile_trasporti=True)
    o['db'].add(vehicle); o['db'].commit()
    # This is the exact missing-column failure masked by old SQLite migrations.
    with pytest.raises(DBAPIError):
        o['db'].query(Veicolo).all()
    o['db'].rollback()
    for _ in range(2):
        ensure_model_columns(engine, (Base.metadata, SQLModel.metadata))
    assert set(Veicolo.__table__.columns.keys()) <= {c['name'] for c in inspect(engine).get_columns('veicoli')}
    restored = o['db'].query(Veicolo).one()
    assert restored.targa == 'TEST-VEHICLE' and restored.anno is None
    o['actor'][0] = o['manager']
    for path in ('/manager/veicoli', '/manager/trasporti', '/manager/trasporti/nuovo'):
        response = o['client'].get(path)
        assert response.status_code == 200, path
        assert 'TEST-VEHICLE' in response.text


def test_copy_work_week_preserves_weekend_and_existing_entries(operations):
    o = operations
    monday = date(2026, 9, 14)
    with Session(o['db'].get_bind()) as db:
        records = [PersonalePresenza(personale_id=o['person'].id, attendance_date=monday+timedelta(days=i),
                                     status='WORK', hours=hours) for i, hours in [(0,8),(2,6),(5,3),(6,2)]]
        db.add_all(records); db.commit()
        assert copy_week_attendance_from_monday(db,o['person'].id,monday) == (3,0,True)
        db.commit()
        assert copy_week_attendance_from_monday(db,o['person'].id,monday,overwrite=True) == (0,4,True)
        db.commit()
        rows = {r.attendance_date.weekday():r.hours for r in db.query(PersonalePresenza).all()}
        assert rows == {0:8,1:8,2:8,3:8,4:8,5:3,6:2}


def test_weekend_visibility_and_save_are_explicit(operations):
    o = operations
    o['actor'][0] = o['manager']
    def session():
        with Session(o['db'].get_bind()) as db:
            yield db
    main.app.dependency_overrides[get_session] = session
    url = '/manager/personale/presenze?week_start=2026-09-16'
    response = o['client'].get(url)
    assert response.status_code == 200
    assert response.text.count('class="attendance-day"') == 5
    response = o['client'].get(url+'&show_saturday=true')
    assert response.text.count('class="attendance-day"') == 6
    response = o['client'].get(url+'&show_sunday=true')
    assert response.text.count('class="attendance-day"') == 6
    response = o['client'].post('/manager/personale/presenze', data={
        'personale_id':o['person'].id, 'attendance_date':'2026-09-20', 'week_start':'2026-09-14',
        'status':'WORK','hours':'3','show_saturday':'false','show_sunday':'true'
    }, follow_redirects=False)
    assert response.status_code == 303
    assert 'show_sunday=true' in response.headers['location']
    assert o['client'].get(response.headers['location']).text.count('class="attendance-day"') == 6
    hidden = o['client'].get(url)
    assert 'Sono presenti registrazioni nel weekend' in hidden.text
    month = o['client'].get('/manager/personale/presenze?view=month&month=2026-09')
    assert month.status_code == 200
