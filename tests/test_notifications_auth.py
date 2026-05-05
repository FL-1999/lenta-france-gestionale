from fastapi.testclient import TestClient
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import create_access_token
from database import get_db
from main import app
from models import Base, Notification, Role, RoleEnum, User, UserRole


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


    def test_recent_notifications_returns_renderable_payload(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        own_notification = Notification(
            notification_type="test",
            message="Nuova notifica",
            recipient_user_id=self.user.id,
            target_url="/manager/report",
            is_read=False,
        )
        other_user = User(
            email="capo.notifications@example.com",
            full_name="Capo Notifications",
            hashed_password="test-secret",
            role=RoleEnum.caposquadra,
            is_active=True,
        )
        self.db.add(other_user)
        self.db.flush()
        foreign_notification = Notification(
            notification_type="test",
            message="Notifica altro utente",
            recipient_user_id=other_user.id,
            target_url="/capo/dashboard",
            is_read=False,
        )
        self.db.add_all([own_notification, foreign_notification])
        self.db.commit()

        response = self.client.get("/api/notifications/recent")

        assert response.status_code == 200
        payload = response.json()
        assert "notifications" in payload
        assert len(payload["notifications"]) == 1
        notification = payload["notifications"][0]
        assert notification["message"] == "Nuova notifica"
        assert notification["url"] == "/manager/report"
        assert notification["is_read"] is False
        assert "created_at" in notification

    def test_recent_notifications_includes_old_unread_items(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        old_unread = Notification(
            notification_type="test",
            message="Notifica non letta vecchia",
            recipient_user_id=self.user.id,
            is_read=False,
            created_at=datetime.utcnow() - timedelta(days=45),
        )
        self.db.add(old_unread)
        self.db.commit()

        count_response = self.client.get("/api/notifications/unread-count")
        recent_response = self.client.get("/api/notifications/recent")

        assert count_response.status_code == 200
        assert count_response.json()["unread_count"] == 1
        assert recent_response.status_code == 200
        payload = recent_response.json()
        assert len(payload["notifications"]) == 1
        assert payload["notifications"][0]["message"] == "Notifica non letta vecchia"
