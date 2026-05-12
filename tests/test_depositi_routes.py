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
                "zip_code": "59000",
                "province": "Nord",
                "country": "France",
                "lat": "50.6292",
                "lng": "3.0573",
                "note": "Note test",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)
        self.assertEqual(create_response.headers["location"], "http://testserver/manager/depositi")

        list_response = self.client.get("/manager/depositi", cookies={"lang": "it"})
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(f"Deposito test {unique}", list_response.text)
        self.assertNotIn("Nessun deposito registrato", list_response.text)

        session = SessionLocal()
        try:
            depot = session.query(Depot).filter(Depot.name == f"Deposito test {unique}").first()
            self.assertIsNotNone(depot)
            depot_id = depot.id
            self.assertEqual(depot.city, "Lille")
            self.assertAlmostEqual(depot.lat, 50.6292)
            self.assertTrue(depot.is_active)
        finally:
            session.close()

        update_response = self.client.post(
            f"/manager/depositi/{depot_id}",
            data={
                "name": f"Deposito test {unique} aggiornato",
                "address": "Via Milano 20",
                "city": "Paris",
                "zip_code": "75001",
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
            self.assertEqual(updated.zip_code, "75001")
            self.assertFalse(updated.is_active)
        finally:
            session.close()

    def test_manager_depositi_list_shows_inactive_depots(self) -> None:
        unique = uuid4().hex[:10]
        depot_name = f"000 Deposito inattivo {unique}"
        session = SessionLocal()
        try:
            session.add(Depot(name=depot_name, city="Nice", is_active=False))
            session.commit()
        finally:
            session.close()

        response = self.client.get("/manager/depositi?per_page=100", cookies={"lang": "it"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(depot_name, response.text)

    def test_manager_depositi_duplicate_name_shows_clear_error(self) -> None:
        unique = uuid4().hex[:10]
        existing_name = f"Deposito duplicato {unique}"
        session = SessionLocal()
        try:
            session.add(Depot(name=existing_name, city="Lyon"))
            session.commit()
        finally:
            session.close()

        response = self.client.post(
            "/manager/depositi/nuovo",
            data={
                "name": existing_name,
                "address": "Rue Test 1",
                "city": "Lyon",
                "zip_code": "69000",
                "province": "Rhône",
                "country": "France",
                "is_active": "on",
            },
            follow_redirects=False,
            cookies={"lang": "it"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Deposito già esistente", response.text)

        session = SessionLocal()
        try:
            count = session.query(Depot).filter(Depot.name == existing_name).count()
            self.assertEqual(count, 1)
        finally:
            session.close()



if __name__ == "__main__":
    unittest.main()
