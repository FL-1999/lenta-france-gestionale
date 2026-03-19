import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, engine
from main import app
from models import RoleEnum


class MagazzinoRolePermissionsTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=10,
                role=RoleEnum.magazzino,
                full_name="Operatore Magazzino",
                is_magazzino_manager=True,
            )
        )

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_magazzino_can_open_logistics_pages(self) -> None:
        for path in (
            "/manager/magazzino",
            "/manager/magazzino/richieste",
            "/manager/depositi",
        ):
            response = self.client.get(path, cookies={"lang": "it"})
            self.assertEqual(response.status_code, 200, path)

    def test_magazzino_cannot_open_manager_dashboard(self) -> None:
        response = self.client.get("/manager/dashboard", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 403)

    def test_magazzino_cannot_open_users_or_sites_pages(self) -> None:
        for path in (
            "/manager/utenti",
            "/manager/cantieri",
            "/manager/depositi/nuovo",
            "/manager/trasporti/viaggi/nuovo",
            "/manager/magazzino/categorie",
        ):
            response = self.client.get(path, cookies={"lang": "it"})
            self.assertEqual(response.status_code, 403, path)


if __name__ == "__main__":
    unittest.main()
