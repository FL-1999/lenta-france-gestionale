import os
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import Fiche, Site, SiteCoupe, SiteCoupeAssignment
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="Browser checks opt-in")


def test_descriptions_phone_edit_and_a4_elevations(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with Session(engine) as db:
        db.get(Site, ids["site"]).numero_totale_paratie = 2
        coupe = SiteCoupe(site_id=ids["site"], nome="Coupe 2", quota_tn=14.5, quota_testa=13.5,
                          quota_partenza_scavo=13.5, scavo_da_tn=False, quota_fondo_teorica=2.8,
                          profondita_teorica=10.7, spessore=.42, larghezza=6.3,
                          terreno_teorico="0-1 m: Remblais\n1-9 m: Gravier\n9-10.7 m: Limon")
        db.add(coupe); db.flush()
        for number in (1, 2):
            db.add(SiteCoupeAssignment(site_id=ids["site"], coupe_id=coupe.id, numero_elemento=number, tipologia_scavo="paratia"))
        db.commit()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv("PLAYWRIGHT_BROWSER_CHANNEL") or None)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin+"/") else route.abort())
        page.goto(origin+"/login")
        page.locator("#email").fill("smoke-manager@example.com"); page.locator("#password").fill(password)
        page.locator("#login-form button[type=submit]").click(); page.wait_for_url("**/manager/dashboard")
        page.goto(origin+f'/manager/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=1&tipologia_scavo=paratia')
        page.locator("#data_scavo").fill("2026-10-20"); page.locator("#operatore").fill("Squadra collaudo")
        page.locator("#larghezza_pannello").fill("6.3"); page.locator("#profondita_totale").fill("10.7")
        row = page.locator(".strato-row").first
        row.locator("[data-strato-da]").fill("0"); row.locator("[data-strato-a]").fill("1")
        row.locator("[name=strato_materiale]").select_option("sabbia")
        row.locator("[name=strato_granulometria]").select_option("molto_fine")
        page.locator("#add-strato-btn").click()
        row = page.locator(".strato-row").last
        expect(row.locator("[name=strato_granulometria]")).to_have_value("")
        row.locator("[data-strato-da]").fill("1"); row.locator("[data-strato-a]").fill("10.7")
        row.locator("[name=strato_materiale]").select_option("altro")
        expect(row.locator("[name=strato_materiale_altro]")).to_be_visible()
        row.locator("[name=strato_materiale_altro]").fill("Temporaneo")
        row.locator("[name=strato_materiale]").select_option("ciottoli grossi")
        row.locator("[name=strato_granulometria]").select_option("grossolano")
        row.locator("[name=strato_pezzatura]").select_option("50_100")
        row.locator("[name=strato_fini]").select_option("assenti")
        for width in (320, 390, 1440):
            page.set_viewport_size({"width": width, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.set_viewport_size({"width": 390, "height": 844})
        row.locator(".soil-description").scroll_into_view_if_needed()
        page.screenshot(path=str(Path(artifacts)/"soil-description-phone.png"))
        page.locator("[data-fiche-form] button[type=submit]").click()
        page.wait_for_url("**/manager/fiches/*")
        with Session(engine) as db:
            fiche = db.query(Fiche).one(); fid = fiche.id
            assert sorted(fiche.stratigrafie, key=lambda layer: layer.da_profondita)[1].materiale == (
                "ciottoli grossi · grossolano · 50-100 mm · senza frazione fine")
        page.goto(origin+f"/manager/fiches/{fid}/modifica")
        row = page.locator(".strato-row").last
        expect(row.locator("[name=strato_granulometria]")).to_have_value("grossolano")
        expect(row.locator("[name=strato_pezzatura]")).to_have_value("50_100")
        expect(row.locator("[name=strato_fini]")).to_have_value("assenti")
        page.locator("[data-fiche-form] button[type=submit]").click()
        page.wait_for_url(f"**/manager/fiches/{fid}")
        # Native printing and PDF exports must keep the full footer and all soil rows.
        page.context.add_init_script("window.print = () => {}; window.close = () => {};")
        with page.expect_popup() as pending:
            page.locator("[data-print-technical-sheet]").click()
        printed = pending.value
        printed.wait_for_load_state()
        printed.emulate_media(media="print")
        assert printed.locator("#technical-sheet-export").is_visible()
        bounds = printed.evaluate("""() => {
            const box = s => document.querySelector(s).getBoundingClientRect();
            return {sheet:box('#technical-sheet-export').bottom, footer:box('.technical-visa-block').bottom,
                    data:box('.technical-data-column').bottom, last:box('.technical-soil-block:last-child').bottom};
        }""")
        assert bounds["footer"] <= bounds["sheet"] + 1
        assert bounds["last"] <= bounds["data"] + 1
        printed.close()
        response = page.request.get(origin+f"/manager/fiches/{fid}/pdf", timeout=60000)
        assert response.status == 200
        out = Path(artifacts)/"fiche-terreni-a4.pdf"; out.write_bytes(response.body())
        doc = pdfium.PdfDocument(response.body())
        assert len(doc) == 1
        assert doc[0].get_width() == pytest.approx(595.28, abs=1)
        assert doc[0].get_height() == pytest.approx(841.89, abs=1)
        text = doc[0].get_textpage().get_text_range()
        for label in ("Gros cailloux", "Grossier", "Sans fines", "13.50", "12.50", "4.50", "2.80", "13,50", "12,50", "4,50", "2,80"):
            assert label in text
        doc[0].render(scale=1.7).to_pil().save(Path(artifacts)/"fiche-terreni-a4.png")
        doc.close()
        # Dense reports retain all information on legible A4 continuation pages.
        with Session(engine) as db:
            fiche = db.get(Fiche, fid)
            fiche.terreno_teorico = "\n".join(f"{i}-{i+1} m: Gravier {i+1}" for i in range(10))
            fiche.notes = ("Observation complète de contrôle. " * 20) + "FIN DES OBSERVATIONS"
            db.commit()
        response = page.request.get(origin+f"/manager/fiches/{fid}/pdf", timeout=60000)
        assert response.status == 200
        doc = pdfium.PdfDocument(response.body())
        assert len(doc) == 2
        text = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
        assert "Gravier 10" in text and "FIN DES OBSERVATIONS" in text and "Annexe" in text
        for i in range(len(doc)):
            assert doc[i].get_width() == pytest.approx(595.28, abs=1)
            assert doc[i].get_height() == pytest.approx(841.89, abs=1)
            doc[i].render(scale=1.3).to_pil().save(Path(artifacts)/f"fiche-dense-{i+1}.png")
        doc.close()
        # The shared crew-leader form offers the same choices in French.
        crew_context = browser.new_context(viewport={"width": 390, "height": 844})
        crew_context.add_cookies([{"name": "lang", "value": "fr", "url": origin}])
        crew = crew_context.new_page()
        crew.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin+"/") else route.abort())
        crew.goto(origin+"/login")
        crew.locator("#email").fill("smoke-capo@example.com"); crew.locator("#password").fill(password)
        crew.locator("#login-form button[type=submit]").click(); crew.wait_for_url("**/capo/dashboard")
        crew.goto(origin+f'/capo/fiches/nuova?cantiere_id={ids["site"]}&numero_pannello=2&tipologia_scavo=paratia')
        crew.locator("#data_scavo").fill("2026-10-20"); crew.locator("#operatore").fill("Équipe de test")
        crew.locator("#larghezza_pannello").fill("6.3"); crew.locator("#profondita_totale").fill("10.7")
        crew.locator("[data-strato-da]").fill("0"); crew.locator("[data-strato-a]").fill("10.7")
        crew.locator("[name=strato_materiale]").select_option(label="Gros cailloux")
        crew.locator("[name=strato_granulometria]").select_option(label="Grossier")
        crew.locator("[name=strato_pezzatura]").select_option(label=">100 mm")
        crew.locator("[name=strato_fini]").select_option(label="Sans fines")
        crew.locator("[data-fiche-form] button[type=submit]").click()
        crew.wait_for_url("**/capo/dashboard")
        with Session(engine) as db:
            created = db.query(Fiche).filter_by(numero_pannello=2).one()
            assert created.stratigrafie[0].materiale == "ciottoli grossi · grossolano · >100 mm · senza frazione fine"
            assert created.review_status == "pending"
        crew_context.close()
        assert not errors, errors
        browser.close()
