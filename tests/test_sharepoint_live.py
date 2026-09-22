import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session

from test_operations_live import live_operations
from models import RoleEnum, User
from auth import hash_password

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Live browser checks opt-in")


def test_sharepoint_readiness_and_inventory_desktop_mobile_french(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        user = User(email="cloud-admin@example.com", full_name="Cloud Admin", role=RoleEnum.admin,
                    is_active=True, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_BROWSER_CHANNEL") or None)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort())
        page.goto(origin + "/login")
        page.locator("#email").fill("cloud-admin@example.com")
        page.locator("#password").fill(password)
        page.locator("#login-form button[type=submit]").click()
        page.wait_for_url("**/manager/dashboard")
        page.goto(origin + "/admin/sharepoint")
        expect(page.get_by_role("heading", name="In attesa del tecnico")).to_be_visible()
        expect(page.get_by_role("button", name="Verifica collegamento")).to_be_disabled()
        page.get_by_role("button", name="Prepara documenti esistenti").click()
        expect(page.locator(".cloud-workspace")).to_contain_text("originale.txt")
        expect(page.get_by_role("link", name="Scarica copia")).to_have_count(0)
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 2")
        output = Path(".venv/sharepoint-preview")
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        page.get_by_role("button", name="Cambia tema").click()
        page.screenshot(path=str(output / "desktop-dark.png"), full_page=True)
        context.add_cookies([{"name": "lang", "value": "fr", "url": origin}])
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        expect(page.get_by_role("heading", name="En attente du technicien")).to_be_visible()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth + 2")
        page.screenshot(path=str(output / "mobile-fr.png"), full_page=True)
        assert not errors
        browser.close()
