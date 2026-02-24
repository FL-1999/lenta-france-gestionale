import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import Depot, RoleEnum


class DepositiRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_manager_depositi_pages_render(self) -> None:
        list_response = self.client.get("/manager/depositi", cookies={"lang": "it"})
        self.assertEqual(list_response.status_code, 200)

        new_response = self.client.get("/manager/depositi/nuovo", cookies={"lang": "it"})
        self.assertEqual(new_response.status_code, 200)

    def test_manager_depositi_create_and_update(self) -> None:
        unique = uuid4().hex[:10]
        create_response = self.client.post(
            "/manager/depositi/nuovo",
            data={
                "name": f"Deposito test {unique}",
                "address": "Via Roma 10",
                "city": "Lille",
                "zip": "59000",
                "province": "Nord",
                "country": "France",
                "lat": "50.6292",
                "lng": "3.0573",
                "note": "Note test",
                "is_active": "on",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        session = SessionLocal()
        try:
            depot = session.query(Depot).filter(Depot.name == f"Deposito test {unique}").first()
            self.assertIsNotNone(depot)
            depot_id = depot.id
            self.assertEqual(depot.city, "Lille")
            self.assertAlmostEqual(depot.lat, 50.6292)
        finally:
            session.close()

        update_response = self.client.post(
            f"/manager/depositi/{depot_id}",
            data={
                "name": f"Deposito test {unique} aggiornato",
                "address": "Via Milano 20",
                "city": "Paris",
                "zip": "75001",
                "province": "Ile-de-France",
                "country": "France",
                "lat": "48.8566",
                "lng": "2.3522",
                "note": "Nuova nota",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 303)

        session = SessionLocal()
        try:
            updated = session.query(Depot).filter(Depot.id == depot_id).first()
            self.assertIsNotNone(updated)
            self.assertEqual(updated.city, "Paris")
            self.assertEqual(updated.zip, "75001")
            self.assertFalse(updated.is_active)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
