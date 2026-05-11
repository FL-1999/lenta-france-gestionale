from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from starlette.requests import Request

from main import _build_sites_map_data, app, templates
from models import Depot, RoleEnum, Site, SiteStatusEnum, User


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
        role=RoleEnum.caposquadra,
        full_name="Luigi Bianchi",
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
    for total in range(1, 11):
        assert f'value="{total}"' in output


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
