"""Real browser consent/login/redirect, with ChatGPT callback intercepted locally."""
import base64
import hashlib
import os
import ssl
import threading
import ipaddress
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from urllib.parse import urlencode, urlsplit, parse_qs
import httpx
import pytest
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import Session
from models import User, Role, UserRole, RoleEnum
from test_operations_live import live_operations

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Browser opt-in')
ROOT = '/integrations/assistant/oauth'
MCP = '/integrations/assistant/mcp'
CALLBACK = 'https://chatgpt.com/connector_platform_oauth_redirect'


@pytest.fixture
def live_oauth(tmp_path, monkeypatch):
    # A local TLS proxy exercises real Secure cookies and browser redirects.
    class Proxy(BaseHTTPRequestHandler):
        def forward(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            headers = {k: v for k, v in self.headers.items() if k.lower() != 'content-length'}
            headers['X-Forwarded-Proto'] = 'https'
            response = httpx.request(self.command, live[0] + self.path, headers=headers, content=body)
            self.send_response(response.status_code)
            for key, value in response.headers.multi_items():
                if key.lower() not in ('content-length', 'transfer-encoding', 'content-encoding', 'connection'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        do_GET = do_POST = forward
        def log_message(self, *args):
            pass
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    public = f'https://127.0.0.1:{proxy.server_port}'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'test-cert.pem', tmp_path / 'test-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    proxy.socket = tls.wrap_socket(proxy.socket, server_side=True)
    for key, value in dict(ASSISTANT_API_ENABLED='true', ASSISTANT_OWNER_ID='1',
        ASSISTANT_TOKEN_SHA256='a' * 64, ASSISTANT_PUBLIC_ORIGIN=public,
        ASSISTANT_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z').items():
        monkeypatch.setenv(key, value)
    generator = live_operations.__wrapped__(tmp_path)
    live = next(generator)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    try:
        with Session(live[1]) as db:
            owner = db.query(User).filter_by(email='smoke-manager@example.com').one()
            assert owner.id == 1
            role = db.query(Role).filter_by(name=RoleEnum.admin).first()
            if role is None:
                role = Role(name=RoleEnum.admin); db.add(role); db.flush()
            owner.role = RoleEnum.admin; owner.user_roles = [UserRole(role=role)]; db.commit()
        yield live, public
    finally:
        proxy.shutdown(); proxy.server_close(); thread.join()
        generator.close()


def test_browser_oauth_login_consent_and_revoke(live_oauth):
    live, public = live_oauth
    origin, engine, ids, password, out = live
    client = httpx.post(origin + ROOT + '/register', json={'redirect_uris': [CALLBACK], 'token_endpoint_auth_method': 'none'}).json()['client_id']
    verifier = 'v' * 64
    params = dict(client_id=client, redirect_uri=CALLBACK, response_type='code', state='browser-state',
        resource=public + MCP, scope='lenta.read lenta.prepare lenta.fiches.submit', code_challenge_method='S256',
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv('PLAYWRIGHT_BROWSER_CHANNEL') or None,
            args=['--host-resolver-rules=MAP chatgpt.com ~NOTFOUND'])
        page = browser.new_page(viewport={'width': 390, 'height': 844}, ignore_https_errors=True)
        def local_only(route):
            url = route.request.url
            if url.startswith(public + '/'):
                route.continue_()
            elif url.startswith(CALLBACK + '?'):
                route.fulfill(status=200, content_type='text/html', body='<h1>Callback di prova ricevuto</h1>')
            else:
                route.abort()
        page.route('**/*', local_only)
        page.goto(public + ROOT + '/authorize?' + urlencode(params))
        page.wait_for_url(public + '/login')
        page.locator('#email').fill('smoke-manager@example.com')
        page.locator('#password').fill(password)
        page.get_by_role('button', name='Entra', exact=True).click()
        expect(page.get_by_role('heading', name='Collega ChatGPT a Lenta')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(out / 'lenta-chatgpt-consent.png'))
        with page.expect_request(lambda request: request.url.startswith(CALLBACK + '?')) as callback:
            page.get_by_role('button', name='Autorizza ChatGPT', exact=True).click()
        query = parse_qs(urlsplit(callback.value.url).query)
        assert query['state'] == ['browser-state'] and query['iss'] == [public]
        tokens = httpx.post(origin + ROOT + '/token', data={'grant_type': 'authorization_code',
            'client_id': client, 'redirect_uri': CALLBACK, 'code': query['code'][0],
            'code_verifier': verifier, 'resource': public + MCP})
        assert tokens.status_code == 200, tokens.text
        headers = {'Authorization': 'Bearer ' + tokens.json()['access_token']}
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'lenta_sites', 'arguments': {}}}
        assert httpx.post(origin + MCP, json=body, headers=headers).json()['result']['isError'] is False
        page.goto(public + '/integrations/assistant/connections')
        page.get_by_role('button', name='Revoca tutti i collegamenti ChatGPT').click()
        expect(page.get_by_text('Nessun collegamento ChatGPT attivo.')).to_be_visible()
        assert httpx.post(origin + MCP, json=body, headers=headers).status_code == 401
        browser.close()
