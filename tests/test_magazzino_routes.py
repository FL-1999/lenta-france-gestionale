import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import MagazzinoCategoria, MagazzinoMacro, RoleEnum


class MagazzinoRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)
        self.unique = uuid4().hex[:8]

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_manager_magazzino_list_renders(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get("/manager/magazzino", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Magazzino", response.text)

    def test_categorie_new_form_shows_existing_macros(self) -> None:
        macro_name = f"Macro Test {self.unique}"
        with SessionLocal() as db:
            db.add(MagazzinoMacro(name=macro_name))
            db.commit()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.get(
            "/manager/magazzino/categorie/nuova", cookies={"lang": "it"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(macro_name, response.text)
        self.assertIn("➕ Crea nuova macro", response.text)

    def test_categorie_create_with_existing_macro(self) -> None:
        macro_name = f"Macro Existing {self.unique}"
        category_name = f"Categoria Existing {self.unique}"
        with SessionLocal() as db:
            macro = MagazzinoMacro(name=macro_name)
            db.add(macro)
            db.commit()
            db.refresh(macro)
            macro_id = macro.id

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/magazzino/categorie/nuova",
            data={
                "nome": category_name,
                "ordine": "1",
                "icon": "📦",
                "color": "indigo",
                "macro_id": str(macro_id),
                "attiva": "on",
            },
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            created = (
                db.query(MagazzinoCategoria)
                .filter(MagazzinoCategoria.nome == category_name)
                .first()
            )
            self.assertIsNotNone(created)
            assert created is not None
            self.assertEqual(created.macro_id, macro_id)
            self.assertEqual(created.macro, macro_name)

    def test_categorie_create_with_new_macro(self) -> None:
        macro_name = f"Macro New {self.unique}"
        category_name = f"Categoria New {self.unique}"
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/magazzino/categorie/nuova",
            data={
                "nome": category_name,
                "ordine": "2",
                "icon": "📦",
                "color": "indigo",
                "macro_id": "__new__",
                "new_macro_name": macro_name,
                "attiva": "on",
            },
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            created_macro = (
                db.query(MagazzinoMacro).filter(MagazzinoMacro.name == macro_name).first()
            )
            self.assertIsNotNone(created_macro)
            created_category = (
                db.query(MagazzinoCategoria)
                .filter(MagazzinoCategoria.nome == category_name)
                .first()
            )
            self.assertIsNotNone(created_category)
            assert created_macro is not None and created_category is not None
            self.assertEqual(created_category.macro_id, created_macro.id)
            self.assertEqual(created_category.macro, created_macro.name)

    def test_macro_create_route_creates_macro(self) -> None:
        macro_name = f"Macro Modal {self.unique}"
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/magazzino/macro/nuova",
            data={"name": macro_name},
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            created_macro = (
                db.query(MagazzinoMacro).filter(MagazzinoMacro.name == macro_name).first()
            )
            self.assertIsNotNone(created_macro)


if __name__ == "__main__":
    unittest.main()
