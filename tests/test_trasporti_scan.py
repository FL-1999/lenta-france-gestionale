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
            result = driver_trasporti_viaggi_scan(viaggio_id=viaggio_id, qr_code=qr, db=db, current_user=user)  # scarica
            self.assertEqual(result["action"], "scaricato")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
