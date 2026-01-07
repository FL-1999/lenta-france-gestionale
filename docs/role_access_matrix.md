# Ruoli aggiuntivi: utenti fittizi e accesso atteso

## Utenti fittizi (da creare in ambiente di test)

| Email | Ruolo | Note |
| --- | --- | --- |
| magazzino.test@lenta.local | MAGAZZINO | Solo accesso magazzino (lettura/gestione). |
| contabilita.test@lenta.local | CONTABILITA | Solo report economici in lettura. |
| hr.test@lenta.local | HR | Solo liste personale in lettura. |
| manager.test@lenta.local | MANAGER | Accesso manager completo. |
| admin.test@lenta.local | ADMIN | Accesso completo + amministrazione. |
| capo.test@lenta.local | CAPOSQUADRA | Accesso capo squadra (rapportini, magazzino capo). |

## Cosa devono vedere (e non vedere)

- **MAGAZZINO**
  - ✅ Navigazione: Magazzino + Home magazzino.
  - ❌ Nessun accesso a report economici, personale, cantieri, fiches.
  - ✅ Accesso diretto alle pagine `/manager/magazzino/*`.
  - ❌ Accesso diretto a `/manager/rapportini`, `/manager/personale`, `/manager/cantieri`, `/manager/fiches` → 403.

- **CONTABILITA**
  - ✅ Navigazione: Report economici.
  - ❌ Nessun accesso a magazzino, personale, cantieri, fiches.
  - ✅ Accesso diretto a `/manager/rapportini` e dettaglio `/manager/rapportini/{id}`.
  - ❌ Accesso diretto a `/manager/magazzino/*`, `/manager/personale` → 403.

- **HR**
  - ✅ Navigazione: Personale (solo lettura).
  - ❌ Nessun accesso a magazzino, report economici, cantieri, fiches.
  - ✅ Accesso diretto a `/manager/personale`.
  - ❌ Accesso diretto a `/manager/personale/new`, `/manager/personale/{id}/modifica` → 403.

- **MANAGER**
  - ✅ Navigazione: Dashboard manager, cantieri, magazzino, report, personale, fiches.
  - ✅ Accesso diretto alle pagine manager.

- **ADMIN**
  - ✅ Tutto (inclusa gestione utenti e impostazioni).

- **CAPOSQUADRA**
  - ✅ Dashboard capo squadra, rapportini capo, magazzino capo.
  - ❌ Nessun accesso a pagine manager.

## Verifica accesso diretto (403)

Esempi di URL da verificare con ruoli non autorizzati:

- `/manager/magazzino`
- `/manager/rapportini`
- `/manager/personale`
- `/manager/cantieri`
- `/manager/fiches`
