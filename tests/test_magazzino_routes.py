import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import (
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMacro,
    MagazzinoMovimento,
    MagazzinoMovimentoTipoEnum,
    RoleEnum,
)


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
        self.assertIn('name="macro_id"', response.text)
        self.assertIn("Seleziona macro", response.text)


    def test_macro_new_form_renders(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.get("/manager/magazzino/macro/nuova", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nome macro", response.text)
        self.assertIn('name="ordine"', response.text)

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

    def test_categorie_create_requires_existing_macro(self) -> None:
        category_name = f"Categoria Invalid Macro {self.unique}"
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
                "macro_id": "__new__",
                "new_macro_name": f"Should not create {self.unique}",
                "attiva": "on",
            },
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Seleziona una macro valida.", response.text)

        with SessionLocal() as db:
            created_category = (
                db.query(MagazzinoCategoria)
                .filter(MagazzinoCategoria.nome == category_name)
                .first()
            )
            self.assertIsNone(created_category)


    def test_macros_list_renders_created_macros(self) -> None:
        macro_name = f"Macro List {self.unique}"
        with SessionLocal() as db:
            db.add(MagazzinoMacro(name=macro_name, ordine=3))
            db.commit()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.get("/manager/magazzino/macros", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(macro_name, response.text)

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
            data={"name": macro_name, "ordine": "4", "icon": "🧰", "color": "blue"},
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location", ""), "http://testserver/manager/magazzino/categorie")

        with SessionLocal() as db:
            created_macro = (
                db.query(MagazzinoMacro).filter(MagazzinoMacro.name == macro_name).first()
            )
            self.assertIsNotNone(created_macro)
            assert created_macro is not None
            self.assertEqual(created_macro.ordine, 4)
            self.assertEqual(created_macro.icon, "🧰")
            self.assertEqual(created_macro.color, "blue")

    def test_macro_create_accepts_macros_endpoint_and_order_field(self) -> None:
        macro_name = f"Macro Endpoint {self.unique}"
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/magazzino/macros",
            data={"name": macro_name, "order": "8", "icon": "📦", "color": "green"},
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers.get("location", ""), "http://testserver/manager/magazzino/categorie")

        with SessionLocal() as db:
            created_macro = (
                db.query(MagazzinoMacro).filter(MagazzinoMacro.name == macro_name).first()
            )
            self.assertIsNotNone(created_macro)
            assert created_macro is not None
            self.assertEqual(created_macro.ordine, 8)
            self.assertEqual(created_macro.icon, "📦")
            self.assertEqual(created_macro.color, "green")

    def test_categorie_new_autoselects_macro_from_query_param(self) -> None:
        macro_name = f"Macro Selected {self.unique}"
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

        response = self.client.get(
            f"/manager/magazzino/categorie/nuova?macro_id={macro_id}",
            cookies={"lang": "it"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'<option value="{macro_id}" selected>{macro_name}</option>', response.text)

    def test_macros_list_is_not_polluted_by_category_names(self) -> None:
        macro_name = f"Filtri {self.unique}"
        category_name = f"Filtri Bauer {self.unique}"
        with SessionLocal() as db:
            macro = MagazzinoMacro(name=macro_name)
            db.add(macro)
            db.commit()
            db.refresh(macro)

            category = MagazzinoCategoria(
                nome=category_name,
                slug=f"filtri-bauer-{self.unique}",
                ordine=1,
                attiva=True,
                macro_id=macro.id,
            )
            db.add(category)
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
        self.assertNotIn(category_name, response.text)

    def test_macro_delete_fails_if_categories_exist(self) -> None:
        macro_name = f"Macro protected {self.unique}"
        with SessionLocal() as db:
            macro = MagazzinoMacro(name=macro_name)
            db.add(macro)
            db.commit()
            db.refresh(macro)
            db.add(
                MagazzinoCategoria(
                    nome=f"Cat {self.unique}",
                    slug=f"cat-{self.unique}",
                    ordine=1,
                    attiva=True,
                    macro_id=macro.id,
                )
            )
            db.commit()
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
            f"/manager/magazzino/macro/{macro_id}/delete",
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("error=La+macro+ha+categorie+associate.", response.headers.get("location", ""))

        with SessionLocal() as db:
            macro_still_exists = db.query(MagazzinoMacro).filter(MagazzinoMacro.id == macro_id).first()
            self.assertIsNotNone(macro_still_exists)

    def test_categoria_delete_route_removes_category(self) -> None:
        with SessionLocal() as db:
            macro = MagazzinoMacro(name=f"Macro delete cat {self.unique}")
            db.add(macro)
            db.commit()
            db.refresh(macro)
            categoria = MagazzinoCategoria(
                nome=f"Cat delete {self.unique}",
                slug=f"cat-delete-{self.unique}",
                ordine=1,
                attiva=True,
                macro_id=macro.id,
            )
            db.add(categoria)
            db.commit()
            categoria_id = categoria.id

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.manager,
                id=1,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            f"/manager/magazzino/categorie/{categoria_id}/delete",
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            categoria_deleted = db.query(MagazzinoCategoria).filter(MagazzinoCategoria.id == categoria_id).first()
            self.assertIsNone(categoria_deleted)

    def test_item_archive_creates_scarico_movement_and_sets_inactive(self) -> None:
        with SessionLocal() as db:
            item = MagazzinoItem(
                nome=f"Item archive {self.unique}",
                codice=f"ARCH-{self.unique}",
                quantita_disponibile=7.5,
                attivo=True,
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            item_id = item.id

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.admin,
                id=1,
                full_name="Test Admin",
                is_magazzino_manager=True,
            )
        )

        response = self.client.post(
            f"/manager/magazzino/{item_id}/elimina",
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            archived_item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
            self.assertIsNotNone(archived_item)
            assert archived_item is not None
            self.assertFalse(archived_item.attivo)
            self.assertEqual(archived_item.quantita_disponibile, 0)

            movement = (
                db.query(MagazzinoMovimento)
                .filter(MagazzinoMovimento.item_id == item_id)
                .order_by(MagazzinoMovimento.id.desc())
                .first()
            )
            self.assertIsNotNone(movement)
            assert movement is not None
            self.assertEqual(movement.tipo, MagazzinoMovimentoTipoEnum.scarico)
            self.assertEqual(movement.quantita, 7.5)
            self.assertEqual(movement.note, "Eliminazione articolo")

    def test_item_archive_with_zero_stock_does_not_create_movement(self) -> None:
        with SessionLocal() as db:
            item = MagazzinoItem(
                nome=f"Item archive zero {self.unique}",
                codice=f"ARCH-ZERO-{self.unique}",
                quantita_disponibile=0,
                attivo=True,
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            item_id = item.id

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                role=RoleEnum.admin,
                id=1,
                full_name="Test Admin",
                is_magazzino_manager=True,
            )
        )

        response = self.client.post(
            f"/manager/magazzino/{item_id}/elimina",
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with SessionLocal() as db:
            archived_item = db.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
            self.assertIsNotNone(archived_item)
            assert archived_item is not None
            self.assertFalse(archived_item.attivo)
            self.assertEqual(archived_item.quantita_disponibile, 0)

            movements_count = (
                db.query(MagazzinoMovimento)
                .filter(MagazzinoMovimento.item_id == item_id)
                .count()
            )
            self.assertEqual(movements_count, 0)


if __name__ == "__main__":
    unittest.main()
