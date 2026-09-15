from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import main
from database import get_db
from models import Base, RoleEnum, User


@pytest.fixture
def account(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    user = User(email="regression@example.com", full_name="Test", hashed_password="untouched",
                role=RoleEnum.manager, is_active=True)
    db.add(user)
    db.commit()
    main.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(main, "SessionLocal", factory)
    yield db, user, TestClient(main.app)
    main.app.dependency_overrides.clear()
    db.close()
    engine.dispose()


@pytest.mark.parametrize("endpoint", ["/api/notifications/unread-count", "/sites/", "/fiches/", "/reports/"])
def test_refresh_token_cannot_authorize_api(account, endpoint):
    db, user, client = account
    token = auth.create_refresh_token(user.email)
    response = client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert not auth.access_token_is_valid(token)


def test_inactive_user_cannot_use_sites_dependency(account):
    db, user, client = account
    token = auth.create_access_token({"sub": user.email, "role": "manager"})
    assert client.get("/sites/", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    user.is_active = False
    db.commit()
    assert client.get("/sites/", headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("role", [RoleEnum.driver, RoleEnum.magazzino, RoleEnum.ferraiolo])
@pytest.mark.parametrize("endpoint", ["/fiches/", "/reports/"])
def test_operational_records_reject_unrelated_roles(account, role, endpoint):
    db, user, client = account
    user.role = role
    db.commit()
    token = auth.create_access_token({"sub": user.email, "role": role.value})
    assert client.get(endpoint, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_access_token_types_and_expiry(account):
    _, user, _ = account
    token = auth.create_access_token({"sub": user.email})
    assert auth.decode_access_token(token)["type"] == "access"
    assert auth.access_token_is_valid(token)
    assert not auth.access_token_is_valid(auth.create_access_token(
        {"sub": user.email}, expires_delta=timedelta(seconds=-10)))
    assert auth.decode_refresh_token(token) is None


def test_bootstrap_never_reactivates_promotes_or_resets_existing_user(account, monkeypatch):
    db, user, _ = account
    user.is_active = False
    db.commit()
    monkeypatch.setattr(main, "ADMIN_EMAIL", user.email)
    monkeypatch.setattr(main, "ADMIN_PASSWORD", "test-bootstrap-password")
    monkeypatch.setenv("ADMIN_FORCE_RESET", "true")
    main.create_initial_admin()
    db.refresh(user)
    assert user.role == RoleEnum.manager
    assert user.is_active is False
    assert user.hashed_password == "untouched"


def test_bootstrap_requires_explicit_credentials(account, monkeypatch):
    db, _, _ = account
    monkeypatch.setattr(main, "ADMIN_EMAIL", None)
    monkeypatch.setattr(main, "ADMIN_PASSWORD", None)
    before = db.query(User).count()
    main.create_initial_admin()
    assert db.query(User).count() == before


def test_secure_cookie_flags(monkeypatch):
    from starlette.responses import Response

    monkeypatch.setattr(main, "COOKIE_SECURE", True)
    monkeypatch.setattr(auth, "COOKIE_SECURE", True)
    response = Response()
    main._set_access_cookie(response, "test-access")
    main._set_refresh_cookie(response, "test-refresh")
    auth.set_current_role_cookie(response, "manager")
    for value in response.headers.getlist("set-cookie"):
        assert "Secure" in value
        assert "HttpOnly" in value
        assert "SameSite=lax" in value
