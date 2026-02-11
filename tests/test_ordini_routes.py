import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from models import (
    MagazzinoItem,
    MagazzinoMacro,
    PurchaseOrder,
    RoleEnum,
    User,
)


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

    def test_create_warehouse_order_with_new_category_auto_creates_items_and_confirm_delivery(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-requester-{unique_token}@example.com",
                full_name="Ordini Requester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            macro = MagazzinoMacro(name=f"Macro test ordini {unique_token}")
            session.add_all([requester, macro])
            session.commit()
            session.refresh(requester)
            session.refresh(macro)
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester.id,
                role=RoleEnum.manager,
                full_name=requester.full_name,
                is_magazzino_manager=False,
            )
        )

        create_response = self.client.post(
            "/manager/ordini/nuovo",
            data={
                "supplier_name": f"Fornitore Test {unique_token}",
                "order_date": "2026-01-15",
                "requester_user_id": str(requester.id),
                "description_text": "Ordine test magazzino",
                "order_kind": "warehouse",
                "site_id": "",
                "warehouse_category_id": "",
                "new_category_name": "Categoria auto creata test",
                "category_mode": "new",
                "macro_id": str(macro.id),
                "macro": "",
                "new_category_macro_id": "",
                "new_macro_name": "",
                "description": ["filtro fb1500"],
                "qty_ordered": ["2"],
                "magazzino_item_id": [""],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        session = SessionLocal()
        try:
            order = (
                session.query(PurchaseOrder)
                .filter(PurchaseOrder.supplier_name == f"Fornitore Test {unique_token}")
                .order_by(PurchaseOrder.id.desc())
                .first()
            )
            self.assertIsNotNone(order)
            self.assertEqual(order.order_kind, "warehouse")
            self.assertIsNotNone(order.warehouse_category_id)
            self.assertEqual(len(order.lines), 1)
            self.assertIsNotNone(order.lines[0].magazzino_item_id)

            item = (
                session.query(MagazzinoItem)
                .filter(MagazzinoItem.id == order.lines[0].magazzino_item_id)
                .first()
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.nome, "filtro fb1500")
            self.assertEqual(item.categoria_id, order.warehouse_category_id)
            self.assertEqual(item.quantita_disponibile, 0.0)

            duplicate_items_count = (
                session.query(MagazzinoItem)
                .filter(
                    MagazzinoItem.categoria_id == order.warehouse_category_id,
                    MagazzinoItem.nome == "filtro fb1500",
                )
                .count()
            )
            self.assertEqual(duplicate_items_count, 1)
            order_id = order.id
            order_line_id = order.lines[0].id
            item_id = item.id
        finally:
            session.close()

        bolla_response = self.client.post(
            f"/manager/ordini/{order_id}/bolle/nuova",
            data={
                "order_line_id": [str(order_line_id)],
                "qty_delivered": ["2"],
            },
            follow_redirects=False,
        )
        self.assertEqual(bolla_response.status_code, 303)

        session = SessionLocal()
        try:
            order = session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
            self.assertIsNotNone(order)
            self.assertEqual(len(order.deliveries), 1)
            delivery_id = order.deliveries[0].id
        finally:
            session.close()

        confirm_response = self.client.post(
            f"/manager/ordini/bolle/{delivery_id}/conferma",
            follow_redirects=False,
        )
        self.assertEqual(confirm_response.status_code, 303)

        session = SessionLocal()
        try:
            item = session.query(MagazzinoItem).filter(MagazzinoItem.id == item_id).first()
            self.assertIsNotNone(item)
            self.assertEqual(item.quantita_disponibile, 2.0)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
