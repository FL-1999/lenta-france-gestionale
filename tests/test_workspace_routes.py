from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import main
import template_context
from auth import get_current_active_user_html
from models import Base, Fiche, FicheTypeEnum, RoleEnum, Site, User


@pytest.fixture
def workspace_client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SQLModel.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        capo = User(email='capo-workspace@example.com', hashed_password='test', role=RoleEnum.caposquadra, is_active=True)
        db.add(capo); db.flush()
        own = Site(name='Cantiere assegnato', caposquadra_id=capo.id, is_active=True)
        other = Site(name='Cantiere riservato', is_active=True)
        db.add_all([own, other]); db.flush()
        for site in (own, other):
            for number in range(1, 32):
                db.add(Fiche(site_id=site.id, created_by_id=capo.id, date=date.today(),
                             numero_pannello=number, fiche_type=list(FicheTypeEnum)[0], description='Collaudo'))
        db.commit()
        # Eagerly load the relationship consumed by the template role helper.
        list(capo.user_roles)
    monkeypatch.setattr(main, 'SessionLocal', sessions)
    monkeypatch.setattr(template_context, 'SessionLocal', sessions)
    main.app.dependency_overrides[get_current_active_user_html] = lambda: capo
    try:
        yield TestClient(main.app), capo
    finally:
        main.app.dependency_overrides.pop(get_current_active_user_html, None)
        engine.dispose()


def test_capo_fiches_only_assigned_sites_and_pagination(workspace_client):
    client, _ = workspace_client
    first = client.get('/capo/fiches')
    assert first.status_code == 200
    assert 'Cantiere assegnato' in first.text
    assert 'Cantiere riservato' not in first.text
    assert first.text.count('<tr><td>') == 30
    second = client.get('/capo/fiches?page=2')
    assert second.status_code == 200
    assert second.text.count('<tr><td>') == 1
    assert 'Cantiere riservato' not in second.text
    assert client.get('/capo/fiches?page=-1').status_code == 200


@pytest.mark.parametrize('role', [RoleEnum.driver, RoleEnum.magazzino, RoleEnum.ferraiolo])
def test_capo_fiches_rejects_other_roles(workspace_client, role):
    client, user = workspace_client
    user.role = role
    assert client.get('/capo/fiches').status_code == 403
