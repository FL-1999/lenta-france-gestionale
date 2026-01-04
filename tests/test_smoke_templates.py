from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from starlette.requests import Request

from main import _build_sites_map_data, app, templates
from models import RoleEnum, Site, SiteStatusEnum, User


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
