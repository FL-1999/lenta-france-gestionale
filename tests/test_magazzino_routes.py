import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from main import app
from models import RoleEnum


class MagazzinoRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_manager_magazzino_list_renders(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get("/manager/magazzino", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Magazzino", response.text)


if __name__ == "__main__":
    unittest.main()
