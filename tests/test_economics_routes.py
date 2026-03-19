from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from auth import get_current_active_user_html
from database import get_db
from main import app
import template_context
from models import (
    Base,
    RoleEnum,
    Site,
    SiteEconomicCategoryEnum,
    SiteEconomicEntry,
    SiteEconomicEntryTypeEnum,
    SiteLaborCostEntry,
    SiteStatusEnum,
    SiteStrutLevel,
    User,
)


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)
SQLModel.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def build_manager_user() -> User:
    return User(
        id=99,
        email="manager@example.com",
        full_name="Manager Test",
        hashed_password="fake",
        role=RoleEnum.manager,
        is_active=True,
    )


def seed_site_with_economics() -> int:
    SQLModel.metadata.drop_all(bind=engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        site = Site(
            name="Cantiere Economico",
            code="ECO-001",
            status=SiteStatusEnum.aperto,
            is_active=True,
            installazione_cantiere_pct=40,
            cordoli_total_m=100,
            cordoli_done_m=55,
            paratie_total_panels=20,
            paratie_done_panels=10,
            pozzi_pompaggio_pct=35,
            rabotage_pct=20,
        )
        db.add(site)
        db.flush()
        db.add(SiteStrutLevel(site_id=site.id, level_index=1, total_struts_level=10, done_struts_level=5))
        db.add_all(
            [
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 1),
                    entry_type=SiteEconomicEntryTypeEnum.revenue,
                    category=SiteEconomicCategoryEnum.ricavi_previsti,
                    amount=10000,
                    description="Budget commessa",
                ),
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 5),
                    entry_type=SiteEconomicEntryTypeEnum.revenue,
                    category=SiteEconomicCategoryEnum.ricavi_fatturati,
                    amount=7000,
                    description="SAL fatturato",
                ),
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 7),
                    entry_type=SiteEconomicEntryTypeEnum.revenue,
                    category=SiteEconomicCategoryEnum.ricavi_maturati,
                    amount=8000,
                    description="Ricavo maturato",
                ),
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 2),
                    entry_type=SiteEconomicEntryTypeEnum.cost,
                    category=SiteEconomicCategoryEnum.materiali,
                    amount=1500,
                ),
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 3),
                    entry_type=SiteEconomicEntryTypeEnum.cost,
                    category=SiteEconomicCategoryEnum.trasporti,
                    amount=600,
                ),
                SiteEconomicEntry(
                    site_id=site.id,
                    entry_date=date(2026, 3, 4),
                    entry_type=SiteEconomicEntryTypeEnum.cost,
                    category=SiteEconomicCategoryEnum.mezzi,
                    amount=400,
                ),
            ]
        )
        db.add(
            SiteLaborCostEntry(
                site_id=site.id,
                work_date=date(2026, 3, 6),
                worker_count=4,
                unit_cost=120,
                notes="Squadra completa",
            )
        )
        db.commit()
        return site.id
    finally:
        db.close()



template_context.get_warehouse_notification_counts = lambda db, user: {
    "total": 0,
    "low_stock": 0,
    "requests": 0,
    "has_any": False,
    "has_low_stock": False,
    "has_requests": False,
}

client = TestClient(app)
app.dependency_overrides[get_db] = override_get_db


def setup_function() -> None:
    app.dependency_overrides[get_db] = override_get_db


def teardown_function() -> None:
    app.dependency_overrides = {get_db: override_get_db}


def test_manager_can_open_site_economics_detail() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.get(f"/manager/cantieri/{site_id}/economics?timeframe=month&start_date=2026-03-01&end_date=2026-03-31")

    assert response.status_code == 200
    assert "Cantiere Economico" in response.text
    assert "€ 480.00" in response.text
    assert "Formula applicata automaticamente" in response.text
    assert "€ 2980.00" in response.text
    assert "€ 4020.00" in response.text


def test_non_manager_cannot_access_economics_area() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = lambda: SimpleNamespace(role=RoleEnum.caposquadra, is_active=True)

    response = client.get(f"/manager/cantieri/{site_id}/economics")

    assert response.status_code == 403


def test_post_labor_cost_entry_computes_total() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.post(
        f"/manager/cantieri/{site_id}/economics/labor",
        data={
            "work_date": "2026-03-08",
            "worker_count": "3",
            "unit_cost": "110",
            "notes": "Turno ridotto",
            "timeframe": "month",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    db = TestingSessionLocal()
    try:
        row = db.query(SiteLaborCostEntry).filter(SiteLaborCostEntry.site_id == site_id, SiteLaborCostEntry.work_date == date(2026, 3, 8)).first()
        assert row is not None
        assert row.total_cost == 330
    finally:
        db.close()
