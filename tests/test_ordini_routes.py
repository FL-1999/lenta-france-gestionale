import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from auth import get_current_active_user_html
from database import Base, SessionLocal, engine
from main import app
from routes.ordini import build_order_email, build_order_mailto_link, fix_mojibake
from models import (
    MagazzinoCategoria,
    MagazzinoItem,
    MagazzinoMacro,
    Depot,
    PurchaseDelivery,
    PurchaseOrder,
    PurchaseOrderLine,
    RoleEnum,
    Site,
    Supplier,
    User,
)


class OrdiniRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        app.dependency_overrides = {}


    def test_fix_mojibake_recovers_latin1_decoded_utf8_text(self) -> None:
        broken = "Commande nÂ° 1\nRÃ©capitulatif\nQuantitÃ©\ndÃ©lais"
        fixed = fix_mojibake(broken)
        self.assertEqual(fixed, "Commande n° 1\nRécapitulatif\nQuantité\ndélais")

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

    def test_manager_ordini_new_renders_without_email_wizard_crash(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get("/manager/ordini/nuovo", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)

    def test_manager_ordini_email_wizard_requires_selected_order(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get("/manager/ordini/" "email-wizard", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Devi prima aprire un ordine.', response.text)

    def test_manager_ordini_email_wizard_redirects_with_order_id(self) -> None:
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )
        response = self.client.get(
            "/manager/ordini/" "email-wizard?order_id=123",
            cookies={"lang": "it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("location"), "http://testserver/manager/ordini/123/email")

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
                "new_category_name": f"Categoria auto creata {unique_token}",
                "category_mode": "new_in_macro",
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
            category_id = item.categoria_id
        finally:
            session.close()

        bolla_response = self.client.post(
            f"/manager/ordini/{order_id}/bolle/nuova",
            data={
                "delivery_number": f"BOL-{unique_token}",
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


    def test_create_warehouse_order_new_macro_creates_macro_and_category(self) -> None:
        # Modalità "new_macro": crea contemporaneamente una nuova macro e una
        # nuova categoria al suo interno, quindi l'ordine e gli articoli.
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-newmacro-{unique_token}@example.com",
                full_name="Ordini NewMacro",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            session.add(requester)
            session.commit()
            session.refresh(requester)
            requester_id = requester.id
            requester_name = requester.full_name
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        macro_name = f"Macro nuova {unique_token}"
        cat_name = f"Categoria nuova {unique_token}"
        response = self.client.post(
            "/manager/ordini/nuovo",
            data={
                "supplier_name": f"Fornitore NM {unique_token}",
                "order_date": "2026-02-01",
                "requester_user_id": str(requester_id),
                "order_kind": "warehouse",
                "category_mode": "new_macro",
                "new_macro_name": macro_name,
                "new_category_name": cat_name,
                "description": ["bullone m12"],
                "qty_ordered": ["5"],
                "magazzino_item_id": [""],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        session = SessionLocal()
        try:
            macro = session.query(MagazzinoMacro).filter(MagazzinoMacro.name == macro_name).first()
            self.assertIsNotNone(macro)
            categoria = (
                session.query(MagazzinoCategoria)
                .filter(MagazzinoCategoria.nome == cat_name)
                .first()
            )
            self.assertIsNotNone(categoria)
            self.assertEqual(categoria.macro_id, macro.id)
        finally:
            session.close()

    def test_api_magazzino_ensure_item_is_idempotent_and_autocreates_technical_category(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-api-{unique_token}@example.com",
                full_name="Ordini API Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            macro = MagazzinoMacro(name=f"Macro API {unique_token}")
            session.add_all([requester, macro])
            session.commit()
            session.refresh(requester)
            session.refresh(macro)
            requester_id = requester.id
            requester_name = requester.full_name
            macro_id = macro.id
            macro_name = macro.name
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        payload = {
            "macro_id": str(macro_id),
            "new_macro_name": "",
            "item_name": "Filtro FB1500",
        }

        first_response = self.client.post("/api/magazzino/ensure-item", json=payload)
        self.assertEqual(first_response.status_code, 200)
        first_data = first_response.json()
        self.assertTrue(first_data.get("ok"))
        self.assertEqual(first_data.get("macro_id"), macro_id)
        self.assertEqual(first_data.get("macro_nome"), macro_name)

        second_response = self.client.post("/api/magazzino/ensure-item", json={**payload, "item_name": "filtro fb1500"})
        self.assertEqual(second_response.status_code, 200)
        second_data = second_response.json()

        self.assertEqual(first_data.get("item_id"), second_data.get("item_id"))
        self.assertEqual(first_data.get("categoria_id"), second_data.get("categoria_id"))

        session = SessionLocal()
        try:
            categoria = session.query(MagazzinoCategoria).filter(MagazzinoCategoria.id == first_data["categoria_id"]).first()
            self.assertIsNotNone(categoria)
            assert categoria is not None
            self.assertEqual(categoria.nome, macro_name)
            self.assertEqual(categoria.macro_id, macro_id)

            items_count = (
                session.query(MagazzinoItem)
                .filter(
                    MagazzinoItem.categoria_id == categoria.id,
                    MagazzinoItem.nome.ilike("filtro fb1500"),
                )
                .count()
            )
            self.assertEqual(items_count, 1)
        finally:
            session.close()


    def test_create_order_with_inline_new_supplier_and_email_redirect(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-supplier-{unique_token}@example.com",
                full_name="Ordini Supplier Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            categoria = MagazzinoCategoria(nome=f"Cat {unique_token}", slug=f"cat-{unique_token}", ordine=99999, attiva=True)
            item = MagazzinoItem(nome="Bulloni", codice=f"B-{unique_token[:5]}", categoria=categoria, quantita_disponibile=0.0, attivo=True)
            session.add_all([requester, categoria, item])
            session.commit()
            session.refresh(requester)
            session.refresh(item)
            requester_id = requester.id
            item_id = item.id
            category_id = item.categoria_id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name="Ordini Supplier Tester",
                is_magazzino_manager=False,
            )
        )

        create_response = self.client.post(
            "/manager/ordini/nuovo",
            data={
                "supplier_name": "",
                "supplier_id": "__new__",
                "new_supplier_name": f"Supplier {unique_token}",
                "new_supplier_email": f"fornitore-{unique_token}@example.com",
                "new_supplier_phone": "",
                "order_date": "2026-02-01",
                "requester_user_id": str(requester_id),
                "description_text": "Ordine con fornitore inline",
                "order_kind": "warehouse",
                "warehouse_category_id": str(category_id),
                "site_id": "",
                "new_category_name": "",
                "category_mode": "existing",
                "macro_id": "",
                "macro": "",
                "new_category_macro_id": "",
                "new_macro_name": "",
                "description": ["Bulloni"],
                "qty_ordered": ["10"],
                "magazzino_item_id": [str(item_id)],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        session = SessionLocal()
        try:
            order = (
                session.query(PurchaseOrder)
                .filter(PurchaseOrder.description == "Ordine con fornitore inline")
                .order_by(PurchaseOrder.id.desc())
                .first()
            )
            self.assertIsNotNone(order)
            assert order is not None
            self.assertIsNotNone(order.supplier_id)
            self.assertEqual(order.supplier_name, f"Supplier {unique_token}")
            order_id = order.id
        finally:
            session.close()

        session = SessionLocal()
        try:
            order = session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
            self.assertIsNotNone(order)
            assert order is not None
            subject, body = build_order_email(order, supplier=order.supplier, lang="fr")
            self.assertIn("Commande n°", subject)
            self.assertIn(f"Supplier {unique_token}", subject)
            self.assertIn("confirmer la prise en charge", body)
            mailto_url = build_order_mailto_link(order, lang="fr")
            self.assertIsNotNone(mailto_url)
            assert mailto_url is not None
            self.assertIn("D%E9tail", mailto_url)
            self.assertIn("n%B0", mailto_url)
        finally:
            session.close()

    def test_create_order_with_inline_new_supplier_and_new_category_redirects(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-inline-{unique_token}@example.com",
                full_name="Ordini Inline Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            macro = MagazzinoMacro(name=f"Macro inline {unique_token}")
            session.add_all([requester, macro])
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            macro_id = macro.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/ordini/nuovo",
            data={
                "supplier_name": "",
                "supplier_id": "__new__",
                "new_supplier_name": f"Supplier inline {unique_token}",
                "new_supplier_email": f"inline-{unique_token}@example.com",
                "new_supplier_phone": "",
                "order_date": "2026-02-01",
                "requester_user_id": str(requester_id),
                "description_text": "Ordine inline completo",
                "order_kind": "warehouse",
                "warehouse_category_id": "__new__",
                "site_id": "",
                "new_category_name": "Categoria inline",
                "category_mode": "new",
                "macro_id": str(macro_id),
                "macro": "",
                "new_category_macro_id": "",
                "new_macro_name": "",
                "description": ["Viti inox"],
                "qty_ordered": ["6"],
                "magazzino_item_id": [""],
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

    def test_manager_fornitori_crud_pages(self) -> None:
        unique_token = uuid4().hex
        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        create_response = self.client.post(
            "/manager/fornitori/nuovo",
            data={
                "name": f"Fornitore {unique_token}",
                "city": "Paris",
                "address": "Rue de Test",
                "zip_code": "75001",
                "province": "Paris",
                "country": "FR",
                "email": f"f-{unique_token}@example.com",
                "phone": "123",
                "vat_number": "FR123",
                "notes": "note",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        list_response = self.client.get(f"/manager/fornitori?q={unique_token}")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn(f"Fornitore {unique_token}", list_response.text)

    def test_create_delivery_without_number_shows_user_friendly_error(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-delivery-{unique_token}@example.com",
                full_name="Ordini Delivery Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            session.add(requester)
            session.flush()

            order = PurchaseOrder(
                order_number=f"TEST-DEL-{unique_token[:8]}",
                supplier_name="Fornitore Test",
                requester_user_id=requester.id,
                status="bozza",
            )
            session.add(order)
            session.flush()

            order_line = PurchaseOrderLine(
                order_id=order.id,
                description="Ricambio",
                qty_ordered=3,
            )
            session.add(order_line)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
            order_line_id = order_line.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            f"/manager/ordini/{order_id}/bolle/nuova",
            data={
                "delivery_number": " ",
                "order_line_id": [str(order_line_id)],
                "qty_delivered": ["1"],
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Inserisci il numero bolla.", response.text)

        session = SessionLocal()
        try:
            deliveries = (
                session.query(PurchaseDelivery)
                .filter(PurchaseDelivery.order_id == order_id)
                .all()
            )
            self.assertEqual(len(deliveries), 0)
        finally:
            session.close()

    def test_save_invoice_without_file_keeps_existing_file(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-invoice-{unique_token}@example.com",
                full_name="Ordini Invoice Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            session.add(requester)
            session.flush()

            order = PurchaseOrder(
                order_number=f"TEST-INV-{unique_token[:8]}",
                supplier_name="Fornitore Test",
                requester_user_id=requester.id,
                status="bozza",
                file_invoice="uploads/invoices/existing-file.pdf",
            )
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            f"/manager/ordini/{order_id}/fattura",
            data={
                "invoice_number": "INV-2026-001",
                "invoice_date": "2026-02-10",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        session = SessionLocal()
        try:
            saved_order = session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
            self.assertIsNotNone(saved_order)
            self.assertEqual(saved_order.invoice_number, "INV-2026-001")
            self.assertEqual(saved_order.invoice_date, date(2026, 2, 10))
            self.assertEqual(saved_order.file_invoice, "uploads/invoices/existing-file.pdf")
        finally:
            session.close()

    def test_invoice_form_uses_multipart_without_required_file(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-invoice-form-{unique_token}@example.com",
                full_name="Ordini Invoice Form Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            order = PurchaseOrder(
                order_number=f"TEST-INVFORM-{unique_token[:8]}",
                supplier_name="Fornitore Test",
                requester_user_id=1,
                status="bozza",
            )
            session.add(requester)
            session.flush()
            order.requester_user_id = requester.id
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.get(f"/manager/ordini/{order_id}/fattura")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<form method="post" enctype="multipart/form-data">', response.text)
        self.assertIn('name="invoice_file"', response.text)
        self.assertNotIn('name="invoice_file" required', response.text)

    def test_manager_ordini_detail_disables_email_button_when_supplier_email_missing(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-detail-{unique_token}@example.com",
                full_name="Ordini Detail Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            order = PurchaseOrder(
                order_number=f"TEST-DETAIL-{unique_token[:8]}",
                supplier_name="Fornitore senza email",
                requester_user_id=1,
                status="bozza",
            )
            session.add(requester)
            session.flush()
            order.requester_user_id = requester.id
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.get(f"/manager/ordini/{order_id}", cookies={"lang": "it"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('title="Email fornitore non disponibile"', response.text)
        self.assertIn('Invia ordine', response.text)

    def test_manager_ordini_email_redirects_back_when_supplier_email_missing(self) -> None:
        unique_token = uuid4().hex

        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-{unique_token}@example.com",
                full_name="Ordini Email Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            order = PurchaseOrder(
                order_number=f"TEST-MAIL-{unique_token[:8]}",
                supplier_name="Fornitore senza email",
                requester_user_id=1,
                status="bozza",
            )
            session.add(requester)
            session.flush()
            order.requester_user_id = requester.id
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.get(
            f"/manager/ordini/{order_id}/email",
            follow_redirects=False,
            cookies={"lang": "it"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn(f"/manager/ordini/{order_id}", response.headers.get("location", ""))
        self.assertIn("Email+fornitore+non+disponibile", response.headers.get("location", ""))


    def test_api_supplier_by_id_returns_contact_data(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            supplier = Supplier(
                name=f"Supplier {unique_token}",
                email=f"supplier-{unique_token}@example.com",
                phone="+33 1 99 99 99 99",
                contact_name="Paul Martin",
                contact_email=f"paul-{unique_token}@example.com",
                is_active=True,
            )
            session.add(supplier)
            session.commit()
            supplier_id = supplier.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=1,
                role=RoleEnum.manager,
                full_name="Test Manager",
                is_magazzino_manager=False,
            )
        )

        response = self.client.get(f"/api/suppliers/{supplier_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["contact_name"], "Paul Martin")
        self.assertTrue(data["contact_email"].startswith("paul-"))

    def test_manager_order_email_wizard_renders_and_preview_returns_mailto(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-{unique_token}@example.com",
                full_name="Ordini Email Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            supplier = Supplier(
                name=f"Fornitore Email {unique_token}",
                email=f"supplier-{unique_token}@example.com",
                contact_name="Mario Rossi",
                contact_email=f"contact-{unique_token}@example.com",
                is_active=True,
            )
            session.add_all([requester, supplier])
            session.flush()

            order = PurchaseOrder(
                order_number=f"ORD-EMAIL-{unique_token[:6]}",
                supplier_name=supplier.name,
                supplier_id=supplier.id,
                requester_user_id=requester.id,
                status="APERTO",
                order_kind="warehouse",
                contact_name=supplier.contact_name,
                recipient_email=supplier.contact_email,
            )
            session.add(order)
            session.flush()

            line = PurchaseOrderLine(
                order_id=order.id,
                description="Tubo acciaio",
                qty_ordered=4,
            )
            session.add(line)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        page_response = self.client.get(f"/manager/ordini/{order_id}/email", cookies={"lang": "it"})
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Email ordine", page_response.text)

        preview_response = self.client.post(
            f"/manager/ordini/{order_id}/email/preview",
            json={
                "lang": "fr",
                "delivery_type": "PICKUP",
                "to_override": "",
            },
        )
        self.assertEqual(preview_response.status_code, 200)
        payload = preview_response.json()
        self.assertEqual(payload.get("to"), f"contact-{unique_token}@example.com")
        self.assertIn("Commande", payload.get("subject", ""))
        self.assertIn("Enlèvement chez le fournisseur", payload.get("subject", ""))
        self.assertNotIn("Ritiro dal fornitore", payload.get("subject", ""))
        self.assertIn("Lieu de livraison : Enlèvement chez le fournisseur", payload.get("body", ""))
        self.assertNotIn("Ritiro dal fornitore", payload.get("body", ""))
        self.assertIn("mailto:", payload.get("mailto_url", ""))
        self.assertIn("n%B0", payload.get("mailto_url", ""))
        self.assertIn("D%E9tail", payload.get("mailto_url", ""))


    def test_order_email_preview_includes_depot_full_address_in_it_and_fr(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-depot-{unique_token}@example.com",
                full_name="Ordini Email Depot Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            supplier = Supplier(
                name=f"Fornitore Depot {unique_token}",
                email=f"supplier-depot-{unique_token}@example.com",
                contact_email=f"contact-depot-{unique_token}@example.com",
                is_active=True,
            )
            depot = Depot(
                name=f"Depot Test {unique_token}",
                address="12 Rue de Test",
                city="Paris",
                zip_code="75001",
                province="Ile-de-France",
                country="France",
                is_active=True,
            )
            session.add_all([requester, supplier, depot])
            session.flush()

            order = PurchaseOrder(
                order_number=f"ORD-DEPOT-{unique_token[:6]}",
                supplier_name=supplier.name,
                supplier_id=supplier.id,
                requester_user_id=requester.id,
                status="APERTO",
                order_kind="warehouse",
            )
            session.add(order)
            session.flush()

            line = PurchaseOrderLine(order_id=order.id, description="Bulloni", qty_ordered=2)
            session.add(line)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
            depot_id = depot.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        it_response = self.client.post(
            f"/manager/ordini/{order_id}/email/preview",
            json={"lang": "it", "delivery_type": "DEPOT", "delivery_depot_id": depot_id},
        )
        self.assertEqual(it_response.status_code, 200)
        self.assertIn("Indirizzo: 12 Rue de Test, 75001 Paris, Ile-de-France, France", it_response.json().get("body", ""))

        fr_response = self.client.post(
            f"/manager/ordini/{order_id}/email/preview",
            json={"lang": "fr", "delivery_type": "DEPOT", "delivery_depot_id": depot_id},
        )
        self.assertEqual(fr_response.status_code, 200)
        self.assertIn("Adresse : 12 Rue de Test, 75001 Paris, Ile-de-France, France", fr_response.json().get("body", ""))

    def test_order_email_preview_uses_override_fields(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-override-{unique_token}@example.com",
                full_name="Ordini Email Override Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            supplier = Supplier(
                name=f"Fornitore Override {unique_token}",
                email=f"supplier-override-{unique_token}@example.com",
                is_active=True,
            )
            session.add_all([requester, supplier])
            session.flush()
            order = PurchaseOrder(
                order_number=f"ORD-OVR-{unique_token[:6]}",
                supplier_name=supplier.name,
                supplier_id=supplier.id,
                requester_user_id=requester.id,
                status="APERTO",
            )
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            f"/manager/ordini/{order_id}/email/preview",
            json={
                "lang": "it",
                "delivery_type": "PICKUP",
                "to_override": "override@example.com",
                "subject_override": "Oggetto custom",
                "body_override": "Corpo custom",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("to"), "override@example.com")
        self.assertEqual(payload.get("subject"), "Oggetto custom")
        self.assertEqual(payload.get("body"), "Corpo custom")
        self.assertIn("subject=Oggetto%20custom", payload.get("mailto_url", ""))


    def test_order_email_preview_handles_emoji_with_utf8_mailto(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-emoji-{unique_token}@example.com",
                full_name="Ordini Email Emoji Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            supplier = Supplier(
                name=f"Fornitore Emoji {unique_token}",
                email=f"supplier-emoji-{unique_token}@example.com",
                is_active=True,
            )
            session.add_all([requester, supplier])
            session.flush()
            order = PurchaseOrder(
                order_number=f"ORD-EMJ-{unique_token[:6]}",
                supplier_name=supplier.name,
                supplier_id=supplier.id,
                requester_user_id=requester.id,
                status="APERTO",
            )
            session.add(order)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            f"/manager/ordini/{order_id}/email/preview",
            json={
                "lang": "it",
                "delivery_type": "PICKUP",
                "subject_override": "Oggetto dèlai",
                "body_override": "Corpo con quantità",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("subject"), "Oggetto dèlai")
        self.assertEqual(payload.get("body"), "Corpo con quantità")
        self.assertIn("Oggetto%20d%E8lai", payload.get("mailto_url", ""))
        self.assertIn("Corpo%20con%20quantit%E0", payload.get("mailto_url", ""))


    def test_order_email_preview_returns_json_when_order_not_found(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-email-missing-{unique_token}@example.com",
                full_name="Ordini Email Missing Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            session.add(requester)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/ordini/999999/email/preview",
            json={"lang": "it", "delivery_type": "PICKUP"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "order_not_found"})


    def test_api_can_create_macro_and_tipologia_for_new_order_form(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-macro-tipologia-{unique_token}@example.com",
                full_name="Ordini Macro Tipologia Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            session.add(requester)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        macro_response = self.client.post(
            "/api/macros",
            json={"name": f"Macro ordine {unique_token}", "description": "desc macro"},
        )
        self.assertEqual(macro_response.status_code, 200)
        macro_payload = macro_response.json()
        self.assertIsNotNone(macro_payload.get("id"))

        tipologia_response = self.client.post(
            "/api/tipologie",
            json={
                "name": f"Tipologia ordine {unique_token}",
                "description": "desc tipologia",
                "macro_id": str(macro_payload["id"]),
            },
        )
        self.assertEqual(tipologia_response.status_code, 200)
        tipologia_payload = tipologia_response.json()
        self.assertIsNotNone(tipologia_payload.get("id"))
        self.assertEqual(tipologia_payload.get("macro_id"), macro_payload["id"])

    def test_create_order_existing_category_ignores_macro(self) -> None:
        # Nel nuovo flusso, in modalità "categoria esistente" la macro non è
        # più un campo a parte: si sceglie direttamente la categoria dalla
        # select raggruppata per macro. Un eventuale macro_id residuo viene
        # ignorato e l'ordine deve essere creato correttamente.
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            requester = User(
                email=f"ordini-mismatch-{unique_token}@example.com",
                full_name="Ordini Mismatch Tester",
                hashed_password="x",
                role=RoleEnum.manager,
                is_active=True,
            )
            supplier = Supplier(
                name=f"Fornitore mismatch {unique_token}",
                email=f"supplier-mismatch-{unique_token}@example.com",
                is_active=True,
            )
            macro_a = MagazzinoMacro(name=f"Macro A {unique_token}")
            macro_b = MagazzinoMacro(name=f"Macro B {unique_token}")
            session.add_all([requester, supplier, macro_a, macro_b])
            session.flush()
            categoria_b = MagazzinoCategoria(
                nome=f"Tipologia B {unique_token}",
                slug=f"tipologia-b-{unique_token}",
                ordine=1,
                attiva=True,
                macro=macro_b,
                macro_id=macro_b.id,
            )
            session.add(categoria_b)
            session.commit()
            requester_id = requester.id
            requester_name = requester.full_name
            supplier_id = supplier.id
            macro_a_id = macro_a.id
            categoria_b_id = categoria_b.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(
                id=requester_id,
                role=RoleEnum.manager,
                full_name=requester_name,
                is_magazzino_manager=False,
            )
        )

        response = self.client.post(
            "/manager/ordini/nuovo",
            data={
                "supplier_id": str(supplier_id),
                "order_date": "2026-01-15",
                "requester_user_id": str(requester_id),
                "description_text": "Ordine test macro/tipologia",
                "order_kind": "warehouse",
                "warehouse_category_id": str(categoria_b_id),
                "category_mode": "existing",
                "macro_id": str(macro_a_id),
                "description": ["item mismatch"],
                "qty_ordered": ["1"],
                "magazzino_item_id": [""],
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

    def test_orders_list_kind_filter_shows_only_closed(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            supplier = Supplier(name=f"Forn kind {unique_token}", is_active=True)
            site = Site(name=f"Cantiere kind {unique_token}", code=f"CK{unique_token[:6]}", is_active=True)
            session.add_all([supplier, site])
            session.flush()
            closed = PurchaseOrder(
                order_number=f"CLOSED-{unique_token}",
                supplier_id=supplier.id,
                order_kind="closed",
                site_id=site.id,
                delivery_type="SITE",
                delivery_site_id=site.id,
                status="APERTO",
            )
            warehouse = PurchaseOrder(
                order_number=f"WH-{unique_token}",
                supplier_id=supplier.id,
                order_kind="warehouse",
                delivery_type="PICKUP",
                status="APERTO",
            )
            session.add_all([closed, warehouse])
            session.commit()
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(id=1, role=RoleEnum.admin, full_name="Admin", is_magazzino_manager=True)
        )
        resp = self.client.get("/manager/ordini?kind=closed", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"CLOSED-{unique_token}", resp.text)
        self.assertNotIn(f"WH-{unique_token}", resp.text)

    def test_delete_supplier_with_orders_requires_force_then_cascades(self) -> None:
        unique_token = uuid4().hex
        session = SessionLocal()
        try:
            supplier = Supplier(name=f"Fornitore del {unique_token}", is_active=True)
            session.add(supplier)
            session.flush()
            order = PurchaseOrder(
                order_number=f"ORD-{unique_token}",
                supplier_id=supplier.id,
                supplier_name=supplier.name,
                order_kind="warehouse",
                status="APERTO",
            )
            session.add(order)
            session.commit()
            supplier_id = supplier.id
            order_id = order.id
        finally:
            session.close()

        app.dependency_overrides[get_current_active_user_html] = (
            lambda: SimpleNamespace(id=1, role=RoleEnum.admin, full_name="Admin", is_magazzino_manager=True)
        )

        # Senza force: bloccato, fornitore e ordine restano.
        blocked = self.client.post(
            f"/manager/fornitori/{supplier_id}/elimina",
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 303)
        session = SessionLocal()
        try:
            self.assertIsNotNone(session.query(Supplier).filter(Supplier.id == supplier_id).first())
        finally:
            session.close()

        # Con force: elimina fornitore e ordini collegati.
        forced = self.client.post(
            f"/manager/fornitori/{supplier_id}/elimina",
            data={"force": "1"},
            follow_redirects=False,
        )
        self.assertEqual(forced.status_code, 303)
        session = SessionLocal()
        try:
            self.assertIsNone(session.query(Supplier).filter(Supplier.id == supplier_id).first())
            self.assertIsNone(session.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first())
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
