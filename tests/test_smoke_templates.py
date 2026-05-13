from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from starlette.requests import Request

from main import (
    _build_site_pali_schema,
    _build_site_panel_schema,
    _build_sites_map_data,
    app,
    get_current_active_user_html,
    templates,
)
from database import Base
from models import (
    Depot,
    Personale,
    Report,
    ReportWorker,
    Fiche,
    FicheTypeEnum,
    RoleEnum,
    Site,
    SiteStatusEnum,
    User,
)


def build_request(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"cookie", b"lang=it"),
        ],
        "scheme": "http",
        "server": ("testserver", 80),
        "app": app,
    }
    return Request(scope)


def build_manager_user() -> SimpleNamespace:
    return SimpleNamespace(
        role=RoleEnum.manager,
        full_name="Mario Rossi",
        is_magazzino_manager=False,
    )


def build_capo_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        role=RoleEnum.caposquadra,
        full_name="Luigi Bianchi",
        email="capo@example.com",
        is_magazzino_manager=False,
    )


def render_template(template_name: str, context: dict) -> str:
    template = templates.get_template(template_name)
    return template.render(context)


def test_manager_home_renders() -> None:
    output = render_template(
        "manager/home_manager.html",
        {
            "request": build_request("/manager/dashboard"),
            "user": build_manager_user(),
            "reports": [],
            "reports_count": 0,
            "chart_reports_last_30_days": [],
            "chart_hours_per_site_30_days": [],
            "chart_reports_by_status": [],
            "cantieri_map_data": [],
            "detail_url_template": "/manager/cantieri/__SITE_ID__",
            "google_maps_api_key": None,
            "nuove_richieste_count": 0,
        },
    )

    assert "Dashboard Manager" in output


def test_capo_home_renders() -> None:
    output = render_template(
        "capo/home_capo.html",
        {
            "request": build_request("/capo/dashboard"),
            "user": build_capo_user(),
            "kpi_reports_today": 0,
            "kpi_hours_this_week": 0,
            "kpi_assigned_sites": 0,
            "kpi_open_reports": 0,
            "cantieri_map_data": [],
            "detail_url_template": "/capo/cantieri/__SITE_ID__",
            "google_maps_api_key": None,
            "nuove_richieste_count": 0,
        },
    )

    assert "Dashboard Caposquadra" in output


def test_cantiere_form_create_renders() -> None:
    output = render_template(
        "manager/cantiere_form.html",
        {
            "request": build_request("/manager/cantieri/nuovo"),
            "user": build_manager_user(),
            "mode": "create",
            "site": None,
            "site_status_values": [status.value for status in SiteStatusEnum],
            "capisquadra": [],
            "google_maps_api_key": None,
        },
    )

    assert "Nuovo cantiere" in output


def test_cantiere_form_edit_renders() -> None:
    site = Site(
        id=1,
        name="Cantiere Milano",
        code="MI-001",
        city="Milano",
        country="Italia",
        address="Via Roma 1",
        lat=45.0,
        lng=9.0,
        status=SiteStatusEnum.aperto,
        is_active=True,
        start_date=date(2024, 1, 1),
    )
    capi = [
        SimpleNamespace(id=1, full_name="Capo Squadra", email="capo@example.com")
    ]

    output = render_template(
        "manager/cantiere_form.html",
        {
            "request": build_request("/manager/cantieri/1/modifica"),
            "user": build_manager_user(),
            "mode": "edit",
            "site": site,
            "site_status_values": [status.value for status in SiteStatusEnum],
            "capisquadra": capi,
            "google_maps_api_key": None,
            "scarichi_recenti": [],
        },
    )

    assert "Modifica cantiere" in output


def test_cantieri_map_data_is_json_serializable() -> None:
    site = Site(
        id=2,
        name="Cantiere Lyon",
        code="LY-001",
        city="Lyon",
        country="France",
        address="Rue Exemple 10",
        lat=45.75,
        lng=4.85,
        status=SiteStatusEnum.aperto,
        is_active=True,
    )
    site.caposquadra = User(
        email="capo@lenta.fr",
        full_name="Capo Lyon",
        hashed_password="fake",
        role=RoleEnum.caposquadra,
    )

    payload = _build_sites_map_data([site])
    serialized = json.dumps(payload)

    assert '"name": "Cantiere Lyon"' in serialized


def test_build_site_panel_schema_marks_completed_panels() -> None:
    site = Site(
        id=9,
        name="Cantiere Schema",
        totale_paratie_da_scavare=4,
    )
    capo = User(
        email="capo-schema@example.com",
        full_name="Capo Schema",
        hashed_password="fake",
        role=RoleEnum.caposquadra,
    )
    fiche = Fiche(
        id=12,
        date=date(2026, 5, 12),
        numero_pannello=2,
        site_id=site.id,
        created_by=capo,
        created_by_id=1,
        fiche_type=FicheTypeEnum.produzione,
        description="Pannello completato",
        hours=7.5,
        notes="Note pannello",
        metri_cubi_gettati=18.0,
    )

    panel_schema = _build_site_panel_schema(site, [fiche])

    assert [panel["number"] for panel in panel_schema] == [1, 2, 3, 4]
    assert panel_schema[0]["status"] == "missing"
    assert panel_schema[1]["status"] == "completed"
    assert panel_schema[1]["fiche_id"] == 12
    assert panel_schema[1]["caposquadra"] == "Capo Schema"
    assert panel_schema[1]["planimetry"] == {
        "x": None,
        "y": None,
        "width": None,
        "height": None,
    }



def test_build_site_schemas_keep_pali_and_paratie_separate() -> None:
    site = Site(
        id=10,
        name="Cantiere Separato",
        numero_totale_paratie=2,
        numero_totale_pali=2,
    )
    paratia = Fiche(
        id=20,
        date=date(2026, 5, 12),
        numero_pannello=1,
        site_id=site.id,
        created_by_id=1,
        fiche_type=FicheTypeEnum.produzione,
        description="Paratia completata",
        tipologia_scavo="paratia",
    )
    palo = Fiche(
        id=21,
        date=date(2026, 5, 12),
        numero_pannello=2,
        site_id=site.id,
        created_by_id=1,
        fiche_type=FicheTypeEnum.produzione,
        description="Palo completato",
        tipologia_scavo="palo",
        diametro_palo=0.8,
    )

    panel_schema = _build_site_panel_schema(site, [paratia, palo])
    pali_schema = _build_site_pali_schema(site, [paratia, palo])

    assert [panel["fiche_id"] for panel in panel_schema] == [20, None]
    assert [palo_item["fiche_id"] for palo_item in pali_schema] == [None, 21]

def test_manager_site_detail_renders_panel_schema() -> None:
    site = Site(
        id=3,
        name="Cantiere Pannelli",
        code="PAN-003",
        status=SiteStatusEnum.aperto,
        totale_paratie_da_scavare=2,
    )
    progress_summary = {
        "installazione_cantiere": {"percent": 0, "status": "Da fare"},
        "cordoli": {"percent": 0, "done": 0, "total": 0},
        "paratie": {"percent": 50, "done": 1, "total": 2},
        "pozzi_pompaggio": {"percent": 0, "status": "Da fare"},
        "rabotage": {"percent": 0, "status": "Da fare"},
        "puntoni": {"percent": 0, "done": 0, "total": 0},
    }

    output = render_template(
        "manager/site_detail.html",
        {
            "request": build_request("/manager/cantieri/3"),
            "user": build_manager_user(),
            "site": site,
            "progress_summary": progress_summary,
            "strut_levels": [],
            "strut_levels_count": 0,
            "panel_schema": [
                {"number": 1, "is_completed": True, "fiche_id": 44},
                {"number": 2, "is_completed": False, "fiche_id": None},
            ],
            "site_tasks": [],
            "open_tasks": [],
            "completed_tasks": [],
            "task_filter": "tutte",
            "site_task_status_values": [],
            "site_task_priority_values": [],
            "manager_users": [],
        },
    )

    assert "Schema pannelli" in output
    assert 'href="http://testserver/manager/fiches/44"' in output
    assert "Fiche non presente" in output
    assert "grid-avanzamento" in output
    assert "cell done" in output
    assert "cell missing" in output
    assert "panel-tile--completed" in output
    assert "panel-tile--missing" in output


def test_capo_site_detail_renders_non_clickable_panel_schema() -> None:
    site = Site(
        id=4,
        name="Cantiere Capo Pannelli",
        code="CAP-004",
        status=SiteStatusEnum.aperto,
        numero_totale_paratie=2,
    )
    progress_summary = {
        "installazione_cantiere": {"percent": 0, "status": "Da fare"},
        "cordoli": {"percent": 0, "done": 0, "total": 0},
        "paratie": {"percent": 50, "done": 1, "total": 2},
        "pali": {"percent": 0, "done": 0, "total": 0},
        "pozzi_pompaggio": {"percent": 0, "status": "Da fare"},
        "rabotage": {"percent": 0, "status": "Da fare"},
        "puntoni": {"percent": 0, "done": 0, "total": 0},
    }

    output = render_template(
        "capo/site_detail.html",
        {
            "request": build_request("/capo/cantieri/4"),
            "user": build_capo_user(),
            "site": site,
            "progress_summary": progress_summary,
            "panel_schema": [
                {"number": 1, "is_completed": True, "fiche_id": 55},
                {"number": 2, "is_completed": False, "fiche_id": None},
            ],
            "pali_schema": [],
            "can_open_fiche_details": False,
            "site_tasks": [],
            "open_tasks": [],
            "completed_tasks": [],
            "can_add_tasks": False,
        },
    )

    assert "Schema pannelli" in output
    assert "grid-avanzamento" in output
    assert "cell done" in output
    assert "cell missing" in output
    assert 'href="http://testserver/manager/fiches/55"' not in output


def test_capo_nuovo_rapportino_renders_with_safe_dicts() -> None:
    output = render_template(
        "capo_nuovo_rapportino.html",
        {
            "request": build_request("/capo/rapportini/nuovo"),
            "user": build_capo_user(),
            "cantieri": [{"id": 7, "name": "Cantiere Safe"}],
            "operai_attivi": [{"id": 11, "label": "Rossi Mario"}],
            "caposquadra_personale": {"id": 3},
            "caposquadra_label": "Luigi Bianchi",
            "nuove_richieste_count": 0,
        },
    )

    assert 'value="7"' in output
    assert 'data-site-name="Cantiere Safe"' in output
    assert 'label: "Rossi Mario"' in output
    assert '<select id="total_personale" name="total_personale"' in output
    assert 'id="numero_operai"' not in output
    assert 'name="numero_operai"' not in output
    assert 'href="/capo/dashboard" class="btn btn-secondary">⬅️ Menu caposquadra' in output
    assert 'window.location.href = "/capo/dashboard?rapportino_created=1"' in output
    assert 'href="/capo/rapportini"' not in output
    for total in range(1, 11):
        assert f'value="{total}"' in output


def test_capo_rapportini_route_lists_only_logged_capo_reports(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        own_report = Report(
            date=date(2026, 5, 6),
            site_name_or_code="Cantiere Capo",
            total_hours=16,
            workers_count=2,
            activities="Getto cemento",
            created_by_id=1,
        )
        other_report = Report(
            date=date(2026, 5, 7),
            site_name_or_code="Cantiere Altro",
            total_hours=8,
            workers_count=1,
            activities="Da non vedere",
            created_by_id=2,
        )
        db.add_all([own_report, other_report])
        db.commit()
    finally:
        db.close()

    import main as main_module
    import template_context as template_context_module

    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(template_context_module, "SessionLocal", TestingSessionLocal)
    app.dependency_overrides[get_current_active_user_html] = build_capo_user
    try:
        client = TestClient(app)
        response = client.get("/capo/rapportini")
    finally:
        app.dependency_overrides.pop(get_current_active_user_html, None)

    assert response.status_code == 200
    assert "Cantiere Capo" in response.text
    assert "Getto cemento" in response.text
    assert "Cantiere Altro" not in response.text
    assert "Da non vedere" not in response.text


def test_capo_dashboard_weekly_hours_sum_only_logged_capo_worker(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)

    today = date.today()
    week_date = today - timedelta(days=today.weekday())

    db = TestingSessionLocal()
    try:
        capo_personale = Personale(
            user_id=1,
            nome="Luigi",
            cognome="Bianchi",
            email="capo@example.com",
            ruolo="Caposquadra",
            attivo=True,
        )
        operaio = Personale(
            nome="Mario",
            cognome="Rossi",
            email="operaio@example.com",
            ruolo="Operaio",
            attivo=True,
        )
        db.add_all([capo_personale, operaio])
        db.flush()

        report = Report(
            date=week_date,
            site_name_or_code="Cantiere Settimana",
            total_hours=16,
            workers_count=2,
            created_by_id=1,
        )
        db.add(report)
        db.flush()
        db.add_all(
            [
                ReportWorker(
                    report_id=report.id,
                    personale_id=capo_personale.id,
                    attendance_date=week_date,
                    hours_worked=8,
                    day_type="WORK",
                ),
                ReportWorker(
                    report_id=report.id,
                    personale_id=operaio.id,
                    attendance_date=week_date,
                    hours_worked=8,
                    day_type="WORK",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    import main as main_module
    import template_context as template_context_module

    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(template_context_module, "SessionLocal", TestingSessionLocal)
    app.dependency_overrides[get_current_active_user_html] = build_capo_user
    try:
        client = TestClient(app)
        response = client.get("/capo/dashboard")
    finally:
        app.dependency_overrides.pop(get_current_active_user_html, None)

    assert response.status_code == 200
    assert "Ore questa settimana" in response.text
    assert '<div class="kpi-value">8.0</div>' in response.text
    assert '<div class="kpi-value">16.0</div>' not in response.text


def test_new_trip_form_renders_with_unified_locations() -> None:
    locations = [
        SimpleNamespace(value="site:1", label="[Cantiere] Milano Centro"),
        SimpleNamespace(value="depot:2", label="[Deposito] Magazzino Nord"),
    ]
    output = render_template(
        "manager/trasporti/new_trip.html",
        {
            "request": build_request("/manager/trasporti/viaggi/nuovo"),
            "user": build_manager_user(),
            "mode": "create",
            "viaggio": None,
            "form_action": "/manager/trasporti/viaggi/nuovo",
            "autisti": [],
            "mezzi": [],
            "locations": locations,
            "form_data": {
                "codice_viaggio": "",
                "data_partenza": "",
                "orario_partenza": "",
                "data_arrivo_prevista": "",
                "arrivo_stimato_manuale": "",
                "autista_id": "",
                "mezzo_id": "",
                "origine_place": "",
                "destinazione_place": "",
                "materiali_attrezzature": "",
                "note": "",
                "tappa_destinazione": ["", "", ""],
                "tipo_attrezzatura": ["", "", ""],
                "quantita": ["1", "1", "1"],
                "richiesta_tappa_idx": ["1", "1", "1"],
            },
        },
    )

    assert "Seleziona un luogo" in output
    assert "[Deposito] Magazzino Nord" in output


def test_deposito_form_renders_with_map_section() -> None:
    depot = Depot(
        id=1,
        name="Deposito Lille",
        address="Rue de Test 12",
        city="Lille",
        zip_code="59000",
        province="Nord",
        country="France",
        lat=50.6292,
        lng=3.0573,
        is_active=True,
    )

    output = render_template(
        "manager/depositi/form.html",
        {
            "request": build_request("/manager/depositi/1"),
            "user": build_manager_user(),
            "depot": depot,
            "form_action": "/manager/depositi/1",
            "google_maps_api_key": None,
        },
    )

    assert "Modifica deposito" in output
    assert "Posizione su mappa" in output


def test_driver_trip_detail_renders_map_section() -> None:
    output = render_template(
        "driver/trasporti/trip_detail.html",
        {
            "request": build_request("/driver/trasporti/viaggi/1"),
            "user": SimpleNamespace(role=RoleEnum.driver, full_name="Autista Demo", is_magazzino_manager=False),
            "viaggio": SimpleNamespace(
                id=1,
                codice_viaggio="TR-001",
                mezzo=None,
                stato=SimpleNamespace(value="programmato"),
                origine_label="[Deposito] Nord",
                destinazione_label="[Cantiere] Centro",
                departure_display="2026-03-20 · 06:30",
                arrival_estimate_display="07:50",
                arrival_estimate_status="automatico",
                materiali_attrezzature="Trapani e tubi",
                note="Ingresso dal cancello nord",
                tappe=[],
                richieste_attrezzature=[],
                assegnazioni_attrezzature=[],
            ),
            "richieste_disponibili": [],
            "trip_route_points": [
                {"name": "Deposito Nord", "role_label": "Origine", "type_label": "Deposito", "lat": 45.0, "lng": 9.0},
                {"name": "Cantiere Centro", "role_label": "Destinazione", "type_label": "Cantiere", "lat": 45.5, "lng": 9.5},
            ],
            "trip_has_any_coordinates": True,
            "trip_has_mappable_route": True,
            "trip_google_maps_url": "https://www.google.com/maps/dir/?api=1",
        },
    )

    assert "Mappa viaggio" in output
    assert "Apri in Google Maps" in output
