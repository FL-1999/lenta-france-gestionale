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
        assert notification["created_at"] == own_notification.created_at.strftime(
            "%d/%m/%Y %H:%M"
        )

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

    def test_recent_notifications_uses_unread_count_role_logic(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        role_notification = Notification(
            notification_type="test",
            message="Notifica ruolo manager",
            recipient_role=RoleEnum.manager,
            target_url="/manager/dashboard",
            is_read=False,
            created_at=datetime.utcnow() - timedelta(days=45),
        )
        self.db.add(role_notification)
        self.db.commit()

        count_response = self.client.get("/api/notifications/unread-count")
        recent_response = self.client.get("/api/notifications/recent")

        assert count_response.status_code == 200
        assert count_response.json()["unread_count"] == 1
        assert recent_response.status_code == 200
        payload = recent_response.json()
        assert payload == {
            "unread_count": 1,
            "notifications": [
                {
                    "id": role_notification.id,
                    "message": "Notifica ruolo manager",
                    "created_at": role_notification.created_at.strftime(
                        "%d/%m/%Y %H:%M"
                    ),
                    "url": "/manager/dashboard",
                    "is_read": False,
                }
            ],
        }

    def test_recent_notifications_shows_all_unread_recent_types_and_limits_to_50(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        for index in range(20):
            self.db.add(
                Notification(
                    notification_type="test",
                    message=f"Letta {index}",
                    recipient_user_id=self.user.id,
                    is_read=True,
                    created_at=datetime.utcnow() - timedelta(minutes=index + 100),
                )
            )
        for index in range(55):
            notification_type = [
                "report_created",
                "fiche_created",
                "machine_note_created",
            ][index % 3]
            self.db.add(
                Notification(
                    notification_type=notification_type,
                    message=f"Non letta {index}",
                    recipient_user_id=self.user.id,
                    is_read=False,
                    created_at=datetime.utcnow() - timedelta(minutes=index),
                )
            )
        self.db.commit()

        response = self.client.get("/api/notifications/recent?limit=99")

        assert response.status_code == 200
        payload = response.json()
        assert payload["unread_count"] == 55
        assert len(payload["notifications"]) == 50
        assert [item["message"] for item in payload["notifications"][:3]] == [
            "Non letta 0",
            "Non letta 1",
            "Non letta 2",
        ]
        assert {item["message"] for item in payload["notifications"]}.isdisjoint(
            {f"Letta {index}" for index in range(20)}
        )
        assert all(item["is_read"] is False for item in payload["notifications"])

    def test_mark_all_sets_unread_counter_to_zero(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        self.db.add_all(
            [
                Notification(
                    notification_type="test",
                    message="Da leggere 1",
                    recipient_user_id=self.user.id,
                    is_read=False,
                ),
                Notification(
                    notification_type="test",
                    message="Da leggere 2",
                    recipient_user_id=self.user.id,
                    is_read=False,
                ),
            ]
        )
        self.db.commit()

        response = self.client.post(
            "/api/notifications/mark-read", json={"mark_all": True}
        )

        assert response.status_code == 200
        assert response.json()["unread_count"] == 0
        assert (
            self.db.query(Notification).filter(Notification.is_read.is_(False)).count()
            == 0
        )

    def test_cleanup_keeps_max_100_direct_notifications_for_user(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        for index in range(105):
            self.db.add(
                Notification(
                    notification_type="test",
                    message=f"Notifica {index}",
                    recipient_user_id=self.user.id,
                    is_read=True,
                    created_at=datetime.utcnow() - timedelta(minutes=index),
                )
            )
        self.db.commit()

        response = self.client.get("/api/notifications/unread-count")

        assert response.status_code == 200
        assert (
            self.db.query(Notification)
            .filter(Notification.recipient_user_id == self.user.id)
            .count()
            == 100
        )

    def test_clear_all_deletes_current_user_notifications(self):
        token = create_access_token(
            data={
                "sub": self.user.email,
                "role": RoleEnum.manager.value,
                "roles": [RoleEnum.manager.value],
            }
        )
        self.client.cookies.set("access_token", f"Bearer {token}")
        self.client.cookies.set("current_role", RoleEnum.manager.value)

        self.db.add(
            Notification(
                notification_type="test",
                message="Da cancellare",
                recipient_user_id=self.user.id,
                is_read=False,
            )
        )
        self.db.commit()

        response = self.client.post("/api/notifications/clear-all")

        assert response.status_code == 200
        assert response.json()["deleted_count"] == 1
        assert response.json()["unread_count"] == 0
        assert self.db.query(Notification).count() == 0
