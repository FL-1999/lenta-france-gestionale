import unittest
from types import SimpleNamespace
from uuid import uuid4

from database import Base, SessionLocal, engine
from models import Attrezzatura, AttrezzaturaStatoEnum, RoleEnum, User
from routes.manager_attrezzature import (
    _category_prefix,
    _next_codice,
    manager_attrezzature_create,
    manager_attrezzature_delete,
    manager_attrezzature_update,
)


class _Req:
    """Finto Request: url_for restituisce una stringa qualsiasi (basta non fallire)."""

    def url_for(self, name, **kwargs):
        return f"/{name}"


class ManagerAttrezzatureTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.user = SimpleNamespace(id=1, role=RoleEnum.manager, is_active=True)

    def test_category_prefix(self) -> None:
        self.assertEqual(_category_prefix("Pompa"), "POMPA")
        self.assertEqual(_category_prefix("perforatrice"), "PERFOR")
        self.assertEqual(_category_prefix("  con spazi & simboli!! "), "CONSPA")
        self.assertEqual(_category_prefix(""), "ATT")

    def test_next_codice_increments_per_category(self) -> None:
        db = SessionLocal()
        try:
            prefix = _category_prefix("Pompa")
            first = _next_codice(db, prefix)
            db.add(Attrezzatura(codice=first, qr_code=first, nome="Pompa 1", tipo="Pompa", stato=AttrezzaturaStatoEnum.disponibile))
            db.commit()
            second = _next_codice(db, prefix)
            self.assertTrue(first.startswith("POMPA-"))
            self.assertNotEqual(first, second)
            self.assertEqual(int(second.split("-")[1]), int(first.split("-")[1]) + 1)
        finally:
            db.close()

    def test_create_generates_code_and_qr(self) -> None:
        db = SessionLocal()
        try:
            cat = f"Cat{uuid4().hex[:5]}"
            resp = manager_attrezzature_create(
                request=_Req(),
                nome="Attrezzo test",
                categoria=cat,
                stato="disponibile",
                posizione_attuale="Deposito",
                db=db,
                current_user=self.user,
            )
            self.assertEqual(resp.status_code, 303)
            created = db.query(Attrezzatura).filter(Attrezzatura.tipo == cat).first()
            self.assertIsNotNone(created)
            self.assertEqual(created.codice, created.qr_code)  # QR codifica il codice
            self.assertTrue(created.codice.startswith(_category_prefix(cat)))
            self.assertEqual(created.stato, AttrezzaturaStatoEnum.disponibile)
        finally:
            db.close()

    def test_update_keeps_code_but_changes_state(self) -> None:
        db = SessionLocal()
        try:
            code = _next_codice(db, "TMP")
            att = Attrezzatura(codice=code, qr_code=code, nome="X", tipo="Tmp", stato=AttrezzaturaStatoEnum.disponibile)
            db.add(att)
            db.commit()
            att_id, orig_code = att.id, att.codice

            manager_attrezzature_update(
                attrezzatura_id=att_id,
                request=_Req(),
                nome="X modificato",
                categoria="Altra",
                stato="manutenzione",
                posizione_attuale=None,
                db=db,
                current_user=self.user,
            )
            refreshed = db.query(Attrezzatura).filter(Attrezzatura.id == att_id).first()
            self.assertEqual(refreshed.codice, orig_code)  # codice stabile
            self.assertEqual(refreshed.nome, "X modificato")
            self.assertEqual(refreshed.stato, AttrezzaturaStatoEnum.manutenzione)
        finally:
            db.close()

    def test_delete_requires_records_delete_permission(self) -> None:
        db = SessionLocal()
        try:
            code = _next_codice(db, "DEL")
            att = Attrezzatura(codice=code, qr_code=code, nome="Y", tipo="Del", stato=AttrezzaturaStatoEnum.disponibile)
            db.add(att)
            db.commit()
            att_id = att.id

            # manager senza records.delete → 403
            from fastapi import HTTPException

            with self.assertRaises(HTTPException) as ctx:
                manager_attrezzature_delete(
                    attrezzatura_id=att_id, request=_Req(), db=db, current_user=self.user
                )
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIsNotNone(db.query(Attrezzatura).filter(Attrezzatura.id == att_id).first())

            # admin (ha records.delete) → elimina
            admin = SimpleNamespace(id=2, role=RoleEnum.admin, is_active=True)
            manager_attrezzature_delete(attrezzatura_id=att_id, request=_Req(), db=db, current_user=admin)
            self.assertIsNone(db.query(Attrezzatura).filter(Attrezzatura.id == att_id).first())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
