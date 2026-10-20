"""Actual browser/mobile sharing flow using disposable accounts and database."""
import os
import json
from uuid import uuid4
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session
from models import NotebookNote, NotebookDraft, NotebookGrant
from services.notebook_ai import Proposal
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Live browser checks opt-in')


def test_notebook_mobile_desktop_and_private_review(live_operations):
    origin, engine, ids, password, artifacts = live_operations
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None)
        owner = browser.new_context(viewport={'width': 390, 'height': 844}, color_scheme='dark')
        reader = browser.new_context(viewport={'width': 1440, 'height': 1000})
        phone, desktop = owner.new_page(), reader.new_page()
        errors, failures = [], []
        for page in (phone, desktop):
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda r: failures.append((r.status, r.url)) if r.status >= 500 else None)
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        def login(page, email, home):
            page.goto(origin+'/login')
            page.locator('#email').fill(email)
            page.locator('#password').fill(password)
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_url('**'+home)
        def ready(page):
            expect(page.locator('#notebook')).not_to_have_attribute('aria-busy', 'true')
        def no_overflow(page):
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert page.locator('#nb-editor').bounding_box()['width'] >= 240
        login(phone, 'smoke-capo@example.com', '/capo/dashboard')
        login(desktop, 'smoke-manager@example.com', '/manager/dashboard')
        phone.goto(origin+f"/appunti?cantiere={ids['site']}")
        ready(phone)
        phone.get_by_role('button', name='+ Nuovo', exact=True).click()
        form = phone.locator('#nb-edit-form')
        expect(form).to_be_visible()
        ready(phone)
        form.locator('[name=title]').fill('Riunione cantiere · P5')
        form.locator('[name=kind]').select_option('meeting')
        form.locator('[name=body]').fill('P5: verificare 6.3 m.\n<script>window.notesXss = true</script>')
        form.locator('[name=when]').fill('20 ottobre 2026, ore 10')
        form.locator('[name=attendees]').fill('Capo Collaudo\nManager Collaudo')
        phone.get_by_role('button', name='+ Aggiungi voce', exact=True).click()
        phone.locator('[data-action-text]').fill('Controllare la misura sul disegno')
        phone.locator('[data-action-assignee]').fill('Capo Collaudo')
        phone.get_by_role('button', name='Salva appunto', exact=True).click()
        expect(phone.locator('#nb-status')).to_have_text('Appunto salvato.')
        ready(phone)
        note_id = int(phone.url.split('note=')[1])
        for width in (320, 390):
            phone.set_viewport_size({'width': width, 'height': 844})
            no_overflow(phone)
        phone.screenshot(path=str(artifacts/'notebook-phone-edit.png'), full_page=True)
        phone.get_by_role('button', name='← Torna all’elenco', exact=True).click()
        expect(phone.locator('#nb-list')).to_be_visible()
        assert phone.locator('.nb-row').bounding_box()['height'] < 180
        phone.screenshot(path=str(artifacts/'notebook-phone-list.png'), full_page=True)
        phone.locator('.nb-row').click()
        expect(form).to_be_visible()
        ready(phone)
        assert (reader.request.get(origin+f'/appunti/{note_id}')).status == 404

        phone.get_by_role('button', name='Condividi', exact=True).click()
        dialog = phone.locator('#nb-dialog')
        expect(dialog).to_be_visible()
        ready(phone)
        person = dialog.locator('.nb-person').filter(has_text='Manager Collaudo')
        person.locator('input[type=checkbox]').check()
        phone.screenshot(path=str(artifacts/'notebook-phone-sharing.png'), full_page=True)
        dialog.get_by_role('button', name='Conferma accessi', exact=True).click()
        expect(dialog).not_to_be_visible()
        ready(phone)
        desktop.goto(origin+f'/appunti?note={note_id}')
        expect(desktop.locator('#nb-editor h2')).to_have_text('Riunione cantiere · P5')
        expect(desktop.locator('#nb-edit-form')).to_have_count(0)
        expect(desktop.locator('#nb-originals')).to_have_count(0)
        assert desktop.evaluate('window.notesXss') is None
        assert (reader.request.get(origin+f'/appunti/{note_id}/originali')).status == 403
        desktop.screenshot(path=str(artifacts/'notebook-desktop-read.png'), full_page=True)

        phone.get_by_role('button', name='Gestisci accessi', exact=True).click()
        ready(phone)
        dialog.get_by_role('button', name='Rendi privato', exact=True).click()
        expect(dialog).not_to_be_visible()
        ready(phone)
        desktop.reload()
        expect(desktop.locator('#nb-error')).to_contain_text('Appunto non trovato')
        expect(desktop.locator('#nb-editor')).not_to_contain_text('verificare 6.3')

        # Different explicit AI actions must not replay the same idempotency key.
        intents = []
        def enabled_listing(route):
            response = route.fetch()
            data = response.json()
            data['ai_enabled'] = True
            route.fulfill(response=response, json=data)
        def simulated_proposal(route):
            intent = route.request.post_data_json
            intents.append(intent)
            route.fulfill(status=200, content_type='application/json', body=json.dumps({
                'id': uuid4().hex, 'mode': intent['mode'],
                'result': Proposal(title='Proposta simulata', body='P5: 6.3 m.').model_dump()}))
        phone.route('**/appunti/data?*', enabled_listing)
        phone.route('**/appunti/*/riordina', simulated_proposal)
        phone.reload()
        ready(phone)
        for label in ('Riordina con AI', 'Prepara verbale'):
            phone.get_by_role('button', name=label, exact=True).click()
            expect(dialog).to_be_visible()
            ready(phone)
            dialog.get_by_role('button', name='Prepara proposta privata', exact=True).click()
            expect(dialog).not_to_be_visible()
            expect(phone.locator('.nb-draft')).to_be_visible()
            ready(phone)
        assert [i['mode'] for i in intents] == ['tidy', 'meeting']
        assert len({i['request_key'] for i in intents}) == 2
        phone.unroute('**/appunti/data?*', enabled_listing)
        phone.unroute('**/appunti/*/riordina', simulated_proposal)

        # Inject only a provider result into the isolated DB; acceptance uses the actual API.
        with Session(engine) as db:
            note = db.get(NotebookNote, note_id)
            db.add(NotebookDraft(id=uuid4().hex, note_id=note.id, owner_id=note.owner_id,
                request_key=uuid4().hex, base_version=note.version, state='ready', mode='meeting',
                result=Proposal(title='Verbale da verificare', kind='meeting',
                    body='Pannello P5: verificare la misura di 6.3 m.').model_dump()))
            db.commit()
        phone.reload()
        expect(phone.locator('.nb-draft')).to_be_visible()
        ready(phone)
        phone.get_by_role('button', name='Accetta bozza privata', exact=True).click()
        expect(form.locator('[name=body]')).to_have_value('Pannello P5: verificare la misura di 6.3 m.')
        ready(phone)
        phone.locator('#nb-originals summary').click()
        expect(phone.locator('#nb-history')).to_contain_text('<script>window.notesXss = true</script>')
        assert phone.evaluate('window.notesXss') is None
        with Session(engine) as db:
            assert db.query(NotebookGrant).count() == 0
            assert db.query(NotebookNote).count() == 1
        phone.set_viewport_size({'width': 1440, 'height': 1000})
        phone.screenshot(path=str(artifacts/'notebook-desktop-editor.png'), full_page=True)
        phone.get_by_role('button', name='Riordina con AI', exact=True).click()
        expect(dialog).to_contain_text('Riordino AI da attivare')
        ready(phone)
        dialog.get_by_role('button', name='Chiudi', exact=True).click()
        phone.get_by_role('button', name='Archivia', exact=True).click()
        expect(phone.locator('#nb-editor .nb-topline')).to_contain_text('Archiviato')
        ready(phone)
        phone.get_by_role('button', name='Ripristina', exact=True).click()
        expect(form).to_be_visible()
        ready(phone)
        # French navigation and the same compact mobile layout.
        owner.add_cookies([{'name': 'lang', 'value': 'fr', 'url': origin}])
        phone.set_viewport_size({'width': 390, 'height': 844})
        phone.reload()
        expect(phone.locator('#notebook h1')).to_have_text('Notes et réunions')
        ready(phone)
        no_overflow(phone)
        phone.screenshot(path=str(artifacts/'notebook-phone-fr.png'), full_page=True)
        assert not errors and not failures, (errors, failures)
        browser.close()
