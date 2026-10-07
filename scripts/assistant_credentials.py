"""Offline provisioning only: never connects to or modifies the gestionale."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description='Genera una credenziale dedicata per il solo assistente personale.')
    parser.add_argument('--owner-id', type=int, required=True, help='ID numerico del proprio profilo amministratore')
    parser.add_argument('--origin', required=True, help='Origine HTTPS del gestionale, senza percorso')
    parser.add_argument('--days', type=int, default=90, help='Validità in giorni, da 1 a 365 (predefinita: 90)')
    args = parser.parse_args()
    origin = args.origin.rstrip('/')
    url = urlsplit(origin)
    if (args.owner_id <= 0 or not 1 <= args.days <= 365 or url.scheme != 'https' or not url.hostname
            or url.username or url.password or url.path or url.query or url.fragment):
        parser.error('ID, durata o origine HTTPS non validi')
    token = 'lenta_assistant_' + secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat(timespec='seconds')
    print('SOLO NEL SECRET STORE DEL FUTURO ASSISTENTE (non nel codice o nelle chat):')
    print('LENTA_ASSISTANT_TOKEN=' + token)
    print('\nNELLE VARIABILI PRIVATE DEL GESTIONALE:')
    print('ASSISTANT_API_ENABLED=true')
    print('ASSISTANT_OWNER_ID=' + str(args.owner_id))
    print('ASSISTANT_PUBLIC_ORIGIN=' + origin)
    print('ASSISTANT_TOKEN_SHA256=' + hashlib.sha256(token.encode()).hexdigest())
    print('ASSISTANT_TOKEN_EXPIRES_AT=' + expires)
    print('\nIl token in chiaro è mostrato solo qui. Non archiviare questo output nei log.')


if __name__ == '__main__':
    main()
