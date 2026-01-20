from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    MagazzinoItem,
    MagazzinoRichiesta,
    MagazzinoRichiestaStatusEnum,
    RoleEnum,
    User,
)
from notifications import get_warehouse_notification_counts


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_get_warehouse_notification_counts_counts_requests() -> None:
    db = _build_session()
    try:
        user = User(
            email="manager@example.com",
            full_name="Manager Test",
            hashed_password="secret",
            role=RoleEnum.manager,
        )
        db.add(user)
        db.flush()

        request = MagazzinoRichiesta(
            richiesto_da_user_id=user.id,
            stato=MagazzinoRichiestaStatusEnum.in_attesa,
        )
        db.add(request)

        item = MagazzinoItem(
            nome="Guanti",
            codice="G-01",
            quantita_disponibile=2,
            soglia_minima=3,
            attivo=True,
        )
        db.add(item)
        db.commit()

        counts = get_warehouse_notification_counts(db, user)

        assert counts["requests"] == 1
        assert counts["has_requests"] is True
        assert counts["low_stock"] == 1
        assert counts["total"] == 2
        assert counts["has_any"] is True
    finally:
        db.close()
