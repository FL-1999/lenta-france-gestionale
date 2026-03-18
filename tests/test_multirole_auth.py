from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth import get_current_active_user_html
from database import get_db
from main import app
from models import Base, Role, RoleEnum, User, UserRole
from permissions import get_user_roles, user_has_role


class TestMultiRoleAuth:
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

        admin_role = Role(name=RoleEnum.admin, description="Admin")
        driver_role = Role(name=RoleEnum.driver, description="Driver")
        self.db.add_all([admin_role, driver_role])
        self.db.flush()

        user = User(
            email="multi@example.com",
            full_name="Multi Role",
            hashed_password="hashed",
            role=RoleEnum.admin,
            can_switch_roles=True,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add_all(
            [
                UserRole(user_id=user.id, role_id=admin_role.id),
                UserRole(user_id=user.id, role_id=driver_role.id),
            ]
        )
        self.db.commit()
        self.user_id = user.id

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_active_user_html] = lambda: SimpleNamespace(
            id=self.user_id,
            email="multi@example.com",
            can_switch_roles=True,
            role=RoleEnum.admin,
        )
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides = {}
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_permissions_helper_reads_all_assigned_roles(self):
        user = self.db.query(User).filter(User.id == self.user_id).first()

        roles = get_user_roles(user)

        assert roles == (RoleEnum.admin, RoleEnum.driver)
        assert user_has_role(user, RoleEnum.driver) is True

    def test_switch_role_updates_active_role_and_redirects(self):
        response = self.client.get("/switch-role/driver", follow_redirects=False)
        updated_user = self.db.query(User).filter(User.id == self.user_id).first()

        assert response.status_code == 303
        assert response.headers["location"] == "/driver/trasporti/viaggi"
        assert updated_user.role == RoleEnum.driver
        assert "access_token" in response.headers.get("set-cookie", "")

    def test_switch_role_rejects_unassigned_role(self):
        response = self.client.get("/switch-role/manager", follow_redirects=False)
        updated_user = self.db.query(User).filter(User.id == self.user_id).first()

        assert response.status_code == 404 or response.status_code == 403
        assert updated_user.role == RoleEnum.admin
