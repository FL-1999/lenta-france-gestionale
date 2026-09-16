"""Opt-in browser checks: RUN_BROWSER_TESTS=1, with Playwright Chromium installed."""
import os
from datetime import date
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from auth import get_current_active_user_html
from database import get_db, engine as app_engine
from main import app
from models import Base, User, RoleEnum, TrasportoViaggio, Attrezzatura, AttrezzaturaStatoEnum

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Browser tests explicitly enabled in CI")


@pytest.fixture(params=[320, 390])
def driver_browser(request):
    # Template badge helpers open their own sessions in the isolated test database.
    Base.metadata.create_all(app_engine)
    SQLModel.metadata.create_all(app_engine)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SQLModel.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email="browser@example.com", full_name="Autista Test", hashed_password="test",
                role=RoleEnum.driver, is_active=True)
    db.add(user)
    db.flush()
    trip = TrasportoViaggio(codice_viaggio="BROWSER", data_partenza=date(2026, 9, 14),
                            origine="Deposito", destinazione="Cantiere", autista_id=user.id)
    equipment = Attrezzatura(codice="TEST-QR", qr_code="TEST-QR", tipo="pompa",
                            nome='<img src=x onerror="window.injected=true">',
                            stato=AttrezzaturaStatoEnum.disponibile)
    db.add_all([trip, equipment])
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_active_user_html] = lambda: user
    client = TestClient(app)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("PLAYWRIGHT_BROWSER_CHANNEL") or None)
        page = browser.new_page(viewport={"width": request.param, "height": 844})
        requests = []

        def route_request(route):
            url = urlsplit(route.request.url)
            if url.netloc != "testserver":
                if "html5-qrcode" in url.path:
                    route.fulfill(content_type="application/javascript", body="window.Html5Qrcode = class { start(a,b,callback) { window.scanQR = callback; return Promise.resolve(); } };")
                else:
                    route.abort()
                return
            path = url.path + ("?" + url.query if url.query else "")
            if "/scan" in path:
                requests.append(path)
            response = client.request(route.request.method, path, content=route.request.post_data,
                                      headers={"Content-Type": route.request.headers.get("content-type", "text/plain")})
            route.fulfill(status=response.status_code, body=response.content,
                          headers={k: v for k, v in response.headers.items() if k not in {"content-length", "content-encoding"}})

        page.route("**/*", route_request)
        page.goto(f"http://testserver/driver/trasporti/viaggi/{trip.id}")
        yield page, requests
        browser.close()
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_mobile_profile_logout_and_driver_navigation(driver_browser):
    page, _ = driver_browser
    expect(page).to_have_title("Carico viaggio")
    account = page.get_by_role("button", name="Menu account")
    expect(account).to_be_visible()
    bounds = account.bounding_box()
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= page.viewport_size["width"]
    account.click()
    expect(page.get_by_role("link", name="Logout")).to_be_visible()
    page.keyboard.press("Escape")
    expect(account).to_be_focused()
    expect(page.get_by_role("link", name="Logout")).to_be_hidden()
    expect(page.locator('.bottom-nav a[href="/driver/trasporti/viaggi"]').first).to_be_visible()
    assert page.locator('a[href="/manager/trasporti"]').count() == 0


def test_scanner_pauses_and_displays_equipment_name_as_text(driver_browser):
    page, requests = driver_browser
    page.locator('#scan-camera').click()
    page.evaluate("scanQR('TEST-QR'); scanQR('TEST-QR');")
    expect(page.locator("#scan-result")).to_contain_text("CARICATO")
    assert len(requests) == 1
    assert page.locator("#scan-result img").count() == 0
    assert page.evaluate("window.injected === true") is False
    page.evaluate("scanQR('TEST-QR')")
    assert len(requests) == 1
    page.locator("#scan-next").click()
    page.locator("#scan-action").select_option("scarico")
    page.evaluate("scanQR('TEST-QR')")
    expect(page.locator("#scan-result")).to_contain_text("SCARICATO")
    assert len(requests) == 2
    assert "action=scarico" in requests[-1]
