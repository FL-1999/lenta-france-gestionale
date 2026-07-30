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
    Fiche,
    FicheTypeEnum,
    PersonalePresenza,
    RoleEnum,
    Site,
    SiteEconomicCategoryEnum,
    SiteEconomicEntry,
    SiteEconomicEntryTypeEnum,
    SiteEconomicAutoParams,
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


def build_admin_user() -> User:
    return User(
        id=100,
        email="admin@example.com",
        full_name="Admin Test",
        hashed_password="fake",
        role=RoleEnum.admin,
        is_active=True,
    )


def seed_site_with_economics() -> int:
    SQLModel.metadata.drop_all(bind=engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        db.add(
            User(
                id=99,
                email="manager@example.com",
                full_name="Manager Test",
                hashed_password="fake",
                role=RoleEnum.manager,
                is_active=True,
            )
        )
        site = Site(
            name="Cantiere Economico",
            code="ECO-001",
            labor_cost_per_person=120,
            material_unit_prices='{"cemento": 120}',
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
                PersonalePresenza(
                    personale_id=1,
                    attendance_date=date(2026, 3, 6),
                    site_id=site.id,
                    status="WORK",
                ),
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
            SiteEconomicAutoParams(
                site_id=site.id,
                costo_manodopera_persona_giorno=120,
                costo_cemento_mc=120,
                created_by_id=99,
                updated_by_id=99,
            )
        )
        db.add(
            Fiche(
                date=date(2026, 3, 6),
                numero_pannello=1,
                site_id=site.id,
                fiche_type=FicheTypeEnum.produzione,
                description="Getto cemento",
                hours=8,
                materiale="cemento",
                metri_cubi_gettati=10,
                created_by_id=99,
            )
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
    app.dependency_overrides = {}


def test_manager_can_open_site_economics_detail() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.get(f"/manager/cantieri/{site_id}/economics?timeframe=month&start_date=2026-03-01&end_date=2026-03-31")

    assert response.status_code == 200
    assert "Cantiere Economico" in response.text
    assert "€ 480.00" in response.text
    assert "Configurazione costi automatici" in response.text
    assert "Serie trend JSON" in response.text
    assert "Sabato rilevato" in response.text
    assert "€ 4180.00" in response.text
    assert "Fiche #1" in response.text
    assert "Margine reale" not in response.text
    assert "Ricavi reali periodo" not in response.text


def test_admin_can_see_margin_data_in_site_economics_detail() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_admin_user

    response = client.get(f"/manager/cantieri/{site_id}/economics?timeframe=month&start_date=2026-03-01&end_date=2026-03-31")

    assert response.status_code == 200
    assert "Margine reale" in response.text
    assert "Ricavi reali periodo" in response.text
    assert "Utile / perdita" in response.text


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
            "is_active": "1",
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


def test_weekend_labor_entry_stays_inactive_by_default() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.post(
        f"/manager/cantieri/{site_id}/economics/labor",
        data={
            "work_date": "2026-03-07",
            "worker_count": "2",
            "unit_cost": "150",
            "notes": "Weekend non confermato",
            "timeframe": "month",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303

    db = TestingSessionLocal()
    try:
        row = db.query(SiteLaborCostEntry).filter(SiteLaborCostEntry.site_id == site_id, SiteLaborCostEntry.work_date == date(2026, 3, 7)).first()
        assert row is not None
        assert row.is_weekend is True
        assert row.is_active is False
        assert row.total_cost == 0
    finally:
        db.close()


def test_trend_data_endpoint_returns_daily_series() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.get(
        f"/manager/cantieri/{site_id}/economics/trend-data?timeframe=month&start_date=2026-03-01&end_date=2026-03-08"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["site_id"] == site_id
    assert payload["series"][0] == {"data": "2026-03-01", "costi": 0.0}
    assert any(row["data"] == "2026-03-06" and row["costi"] == 480.0 for row in payload["series"])


def test_trend_data_endpoint_returns_full_series_for_admin() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_admin_user

    response = client.get(
        f"/manager/cantieri/{site_id}/economics/trend-data?timeframe=month&start_date=2026-03-01&end_date=2026-03-08"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["series"][0] == {"data": "2026-03-01", "costi": 0.0, "ricavi": 10000.0, "margine": 10000.0}


def test_manager_cannot_create_revenue_entry() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.post(
        f"/manager/cantieri/{site_id}/economics/entries",
        data={
            "entry_date": "2026-03-10",
            "entry_type": "revenue",
            "category": "ricavi_fatturati",
            "amount": "100",
            "description": "Tentativo non admin",
            "notes": "",
            "timeframe": "month",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        },
        follow_redirects=False,
    )

    assert response.status_code == 403


def test_manager_can_update_economic_entry_with_tracking() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user
    db = TestingSessionLocal()
    try:
        entry = (
            db.query(SiteEconomicEntry)
            .filter(SiteEconomicEntry.site_id == site_id, SiteEconomicEntry.category == SiteEconomicCategoryEnum.materiali)
            .first()
        )
        assert entry is not None
        entry_id = entry.id
    finally:
        db.close()

    response = client.request(
        "PUT",
        f"/manager/cantieri/{site_id}/economics/entries/{entry_id}",
        data={
            "entry_date": "2026-03-10",
            "entry_type": "cost",
            "category": "attrezzature",
            "amount": "1900.50",
            "description": "Noleggio aggiornato",
            "notes": "Aggiornato da test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["entry"]["category"] == "attrezzature"
    assert payload["entry"]["amount"] == 1900.5

    db = TestingSessionLocal()
    try:
        updated = db.query(SiteEconomicEntry).filter(SiteEconomicEntry.id == entry_id).first()
        assert updated is not None
        assert updated.updated_by_id == 99
        assert updated.category == SiteEconomicCategoryEnum.attrezzature
    finally:
        db.close()


def test_manager_can_delete_economic_entry() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user
    db = TestingSessionLocal()
    try:
        entry = db.query(SiteEconomicEntry).filter(SiteEconomicEntry.site_id == site_id).first()
        assert entry is not None
        entry_id = entry.id
    finally:
        db.close()

    response = client.request("DELETE", f"/manager/cantieri/{site_id}/economics/entries/{entry_id}")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "deleted_id": entry_id}

    db = TestingSessionLocal()
    try:
        deleted = db.query(SiteEconomicEntry).filter(SiteEconomicEntry.id == entry_id).first()
        assert deleted is None
    finally:
        db.close()


def test_auto_cost_config_update_endpoint() -> None:
    site_id = seed_site_with_economics()
    app.dependency_overrides[get_current_active_user_html] = build_manager_user

    response = client.post(
        f"/manager/cantieri/{site_id}/economics/auto-cost-config",
        data={
            "labor_cost_per_person": "145",
            "material_prices_json": '{"cemento": 130, "acciaio": 2.5}',
            "auto_cost_labor_enabled": "1",
            "auto_cost_materials_enabled": "1",
            "manual_material_entries_override_auto": "1",
            "timeframe": "month",
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    db = TestingSessionLocal()
    try:
        site = db.query(Site).filter(Site.id == site_id).first()
        assert site is not None
        assert site.labor_cost_per_person == 145
        assert "acciaio" in (site.material_unit_prices or "")
    finally:
        db.close()
