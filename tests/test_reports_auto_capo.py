from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from database import Base
from models import Personale, RoleEnum, User
from routers.reports import ReportCreate, ensure_capo_personale, _with_auto_capo_worker


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function() -> None:
    SQLModel.metadata.drop_all(bind=engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)


def test_caposquadra_is_created_as_personale_and_prepended_to_report_workers() -> None:
    db = TestingSessionLocal()
    try:
        capo = User(
            email="capo.report@example.com",
            full_name="Luigi Bianchi",
            hashed_password="fake",
            role=RoleEnum.caposquadra,
            is_active=True,
        )
        db.add(capo)
        db.flush()

        capo_personale = ensure_capo_personale(db, capo)
        report_in = ReportCreate(
            date=date(2026, 5, 6),
            site_id=1,
            site_name_or_code="Cantiere Test",
            total_hours=8,
            workers_count=0,
            workers=[],
        )

        workers, workers_count = _with_auto_capo_worker(db, capo, report_in)

        assert workers_count == 1
        assert workers[0].personale_id == capo_personale.id
        assert workers[0].role_label == "Caposquadra (tu)"
    finally:
        db.close()


def test_caposquadra_personale_reuses_existing_email_and_links_user_id() -> None:
    db = TestingSessionLocal()
    try:
        existing_personale = Personale(
            nome="Luigi",
            cognome="Bianchi",
            email="capo.link@example.com",
            ruolo="Caposquadra",
            attivo=True,
        )
        capo = User(
            email="capo.link@example.com",
            full_name="Luigi Bianchi",
            hashed_password="fake",
            role=RoleEnum.caposquadra,
            is_active=True,
        )
        db.add(existing_personale)
        db.add(capo)
        db.flush()

        capo_personale = ensure_capo_personale(db, capo)

        assert capo_personale.id == existing_personale.id
        assert capo_personale.user_id == capo.id
        assert db.query(Personale).count() == 1
    finally:
        db.close()
