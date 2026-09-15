import unittest
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from database import Base, SessionLocal, engine
from models import (
    Attrezzatura,
    AttrezzaturaStatoEnum,
    RoleEnum,
    TrasportoAttrezzaturaViaggio,
    TrasportoViaggio,
    User,
)
from routes.trasporti import driver_trasporti_viaggi_scan


class TrasportiScanTests(unittest.TestCase):
    """Testa direttamente l'handler di scansione (senza passare dal routing HTTP,
    che in questo ambiente di test non registra i router inclusi)."""

    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)

    def _make(self, stato: AttrezzaturaStatoEnum):
        token = uuid4().hex[:8]
        session = SessionLocal()
        try:
            driver = User(
                email=f"driver-{token}@example.com",
                full_name="Autista Test",
                hashed_password="x",
                role=RoleEnum.driver,
                is_active=True,
            )
            session.add(driver)
            session.flush()
            viaggio = TrasportoViaggio(
                codice_viaggio=f"VG-{token}",
                data_partenza=date(2026, 9, 1),
                origine="Deposito",
                destinazione="Cantiere",
                autista_id=driver.id,
            )
            att = Attrezzatura(
                codice=f"POMPA-{token}",
                qr_code=f"ATT-{token.upper()}",
                nome="Pompa bentonite",
                tipo="pompa",
                stato=stato,
            )
            session.add_all([viaggio, att])
            session.commit()
            return driver.id, viaggio.id, att.qr_code, att.id
        finally:
            session.close()

    def test_scan_blocks_equipment_in_maintenance(self) -> None:
        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.manutenzione)
        db = SessionLocal()
        try:
            user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
            result = driver_trasporti_viaggi_scan(viaggio_id=viaggio_id, qr_code=qr, db=db, current_user=user)
            self.assertEqual(result["action"], "bloccato")
            self.assertEqual(result["reason"], "manutenzione")
        finally:
            db.close()

        db = SessionLocal()
        try:
            assigned = (
                db.query(TrasportoAttrezzaturaViaggio)
                .filter(
                    TrasportoAttrezzaturaViaggio.viaggio_id == viaggio_id,
                    TrasportoAttrezzaturaViaggio.attrezzatura_id == att_id,
                )
                .first()
            )
            self.assertIsNone(assigned)  # non caricata
            att = db.query(Attrezzatura).filter(Attrezzatura.id == att_id).first()
            self.assertEqual(att.stato, AttrezzaturaStatoEnum.manutenzione)  # stato invariato
        finally:
            db.close()

    def test_scan_loads_available_equipment(self) -> None:
        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.disponibile)
        db = SessionLocal()
        try:
            user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
            result = driver_trasporti_viaggi_scan(viaggio_id=viaggio_id, qr_code=qr, db=db, current_user=user)
            self.assertEqual(result["action"], "caricato")
        finally:
            db.close()

        db = SessionLocal()
        try:
            att = db.query(Attrezzatura).filter(Attrezzatura.id == att_id).first()
            self.assertEqual(att.stato, AttrezzaturaStatoEnum.in_trasporto)
        finally:
            db.close()

    def test_scan_unloads_equipment_in_transit_on_this_trip(self) -> None:
        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.disponibile)
        db = SessionLocal()
        user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
        try:
            driver_trasporti_viaggi_scan(viaggio_id=viaggio_id, qr_code=qr, db=db, current_user=user)  # carica
            result = driver_trasporti_viaggi_scan(viaggio_id=viaggio_id, qr_code=qr, action="scarico", db=db, current_user=user)  # scarica
            self.assertEqual(result["action"], "scaricato")
        finally:
            db.close()

    def test_repeated_scans_do_not_toggle_load_or_unload(self):
        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.disponibile)
        with SessionLocal() as db:
            user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
            for _ in range(3):
                assert driver_trasporti_viaggi_scan(viaggio_id, qr, db=db, current_user=user)["action"] == "caricato"
            assert db.get(Attrezzatura, att_id).stato == AttrezzaturaStatoEnum.in_trasporto
            for _ in range(3):
                assert driver_trasporti_viaggi_scan(viaggio_id, qr, action="scarico", db=db, current_user=user)["action"] == "scaricato"
            assert db.get(Attrezzatura, att_id).stato == AttrezzaturaStatoEnum.disponibile
            assert driver_trasporti_viaggi_scan(viaggio_id, qr, db=db, current_user=user)["action"] == "bloccato"

    def test_saving_load_preserves_scanned_assignments_and_rejects_partial_invalid_input(self):
        from fastapi import HTTPException
        from starlette.datastructures import FormData
        from models import TrasportoRichiestaAttrezzatura
        from routes.trasporti import _add_trip_load

        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.disponibile)
        with SessionLocal() as db:
            trip = db.get(TrasportoViaggio, viaggio_id)
            req = TrasportoRichiestaAttrezzatura(viaggio_id=viaggio_id, tipo_attrezzatura="pompa", quantita=2)
            db.add(req)
            db.commit()
            user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
            driver_trasporti_viaggi_scan(viaggio_id, qr, db=db, current_user=user)
            for form in [FormData(), FormData({f"req_{req.id}_0": str(att_id)})]:
                _add_trip_load(db, trip, form)
                db.commit()
                assert db.query(TrasportoAttrezzaturaViaggio).filter_by(viaggio_id=viaggio_id).count() == 1
                assert db.get(Attrezzatura, att_id).stato == AttrezzaturaStatoEnum.in_trasporto
            bad_form = FormData({f"req_{req.id}_0": str(att_id), f"req_{req.id}_1": "999999999"})
            with self.assertRaises(HTTPException):
                _add_trip_load(db, trip, bad_form)
            db.rollback()
            assert db.query(TrasportoAttrezzaturaViaggio).filter_by(viaggio_id=viaggio_id).count() == 1
            duplicate_form = FormData({f"req_{req.id}_0": str(att_id), f"req_{req.id}_1": str(att_id)})
            with self.assertRaises(HTTPException):
                _add_trip_load(db, trip, duplicate_form)


    def test_completion_is_idempotent_and_keeps_remaining_equipment_in_transit(self):
        import asyncio
        from fastapi import Request
        from main import app
        from models import MovimentoAttrezzatura, TrasportoStatoEnum
        from routes.trasporti import driver_trasporti_viaggi_stato

        driver_id, viaggio_id, qr, att_id = self._make(AttrezzaturaStatoEnum.disponibile)
        with SessionLocal() as db:
            user = SimpleNamespace(id=driver_id, role=RoleEnum.driver, is_active=True)
            driver_trasporti_viaggi_scan(viaggio_id, qr, db=db, current_user=user)
            async def receive():
                return {"type": "http.request", "body": f"resta_sul_camion={att_id}".encode(), "more_body": False}
            scope = {"type": "http", "method": "POST", "path": "/", "query_string": b"", "scheme": "http",
                     "server": ("testserver", 80), "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
                     "app": app, "router": app.router}
            for _ in range(2):
                request = Request(scope, receive)
                result = asyncio.run(driver_trasporti_viaggi_stato(viaggio_id, request, "completato", db, user))
                assert result.status_code == 303
            assert db.get(TrasportoViaggio, viaggio_id).stato == TrasportoStatoEnum.completato
            assert db.get(Attrezzatura, att_id).stato == AttrezzaturaStatoEnum.in_trasporto
            assert db.query(MovimentoAttrezzatura).filter_by(viaggio_id=viaggio_id).count() == 1
            assert driver_trasporti_viaggi_scan(viaggio_id, qr, action="scarico", db=db, current_user=user)["action"] == "scaricato"
            assert db.get(Attrezzatura, att_id).stato == AttrezzaturaStatoEnum.disponibile



if __name__ == "__main__":
    unittest.main()
