import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from main import app
from models import RoleEnum


class AdminPermissionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_manager_cannot_access_admin_users(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(role=RoleEnum.manager)
        )
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_admin_users(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(role=RoleEnum.admin)
        )
        response = self.client.get("/admin/users")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
