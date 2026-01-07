# Backup & Export

## Esecuzione manuale

Per creare un backup manuale dal server:

```bash
python scripts/backup_db.py
```

Il backup viene salvato nella cartella `backups/` (configurabile con `BACKUP_DIR`).
Il nome file include la data/ora UTC, ad esempio `backup_20240210_153000.sqlite3`.

In alternativa, gli amministratori possono usare la pagina **Backup & Export**
(`Admin → Backup & Export`) per creare un backup e scaricarlo.

## Esecuzione periodica

### Cron (server Linux)

Esempio: backup giornaliero alle 02:00.

```cron
0 2 * * * /usr/bin/env BACKUP_DIR=/var/backups/lenta /usr/bin/python /app/scripts/backup_db.py >> /var/log/lenta_backup.log 2>&1
```

### Render (Cron Jobs)

1. Crea un **Cron Job** nel servizio Render.
2. Usa il comando:

```bash
python scripts/backup_db.py
```

3. Configura le variabili d’ambiente (ad esempio `BACKUP_DIR`).

## Note sicurezza

- Le credenziali non sono salvate nei template.
- Per database diversi da SQLite, usa gli strumenti ufficiali del DB (es. `pg_dump`)
  configurando le credenziali tramite variabili d’ambiente.
