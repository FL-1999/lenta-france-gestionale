import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, engine
from main import app
from models import RoleEnum


class OrdiniRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_manager_ordini_list_renders(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get("/manager/ordini", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)

    def test_manager_ordini_closed_list_renders(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get(
            "/manager/ordini?status=chiuso",
            cookies={"lang": "it"},
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
