from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import create_access_token
from database import get_db
from main import app
from models import Base, Role, RoleEnum, User, UserRole


class TestNotificationsAuth:
    def setup_method(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

        manager_role = Role(name=RoleEnum.manager, description="Manager")
        self.db.add(manager_role)
        self.db.flush()

        user = User(
            email="manager.notifications@example.com",
            full_name="Manager Notifications",
            hashed_password="test-secret",
            role=RoleEnum.manager,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(UserRole(user_id=user.id, role_id=manager_role.id))
        self.db.commit()
        self.user = user

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides = {}
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_unread_count_returns_401_without_auth_cookie(self):
        response = self.client.get("/api/notifications/unread-count")

        assert response.status_code == 401
        assert response.json()["detail"] == "Credenziali non valide o token mancante"

    def test_unread_count_accepts_access_token_cookie(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        response = self.client.get("/api/notifications/unread-count")

        assert response.status_code == 200
        assert response.json()["unread_count"] == 0
