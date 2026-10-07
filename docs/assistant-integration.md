# Integrazione per l'assistente personale Lenta

Questa implementazione prepara il gestionale per un assistente sviluppato in un
progetto separato. È disattivata per impostazione predefinita. Non contiene un
modello AI, non legge email o file esterni e non richiede nuove dipendenze.

## Accesso e operazioni disponibili

Il canale `/api/integrations/v1` usa una credenziale dedicata al singolo ID utente
configurato. L'utente deve essere attivo e avere accesso amministratore, verificato
a ogni richiesta. Gli altri amministratori non possono confermare le proposte.
L'integrazione non accetta i cookie del gestionale né i suoi normali JWT come
credenziali API. Non richiede la password personale dell'amministratore.

| Dati | Lettura | Scrittura in questa versione |
| --- | --- | --- |
| Cantieri e avanzamenti | Elenco, dettaglio, produzione, fasi, contesto pannello/coupe | Nessuna |
| Personale e ore | Anagrafica operativa, presenze, totali per persona e cantiere | Presenze generate con un nuovo rapporto |
| Fiches | Elenco, dettaglio, stratigrafia | Creazione con le validazioni del modulo esistente |
| Rapporti giornalieri | Elenco e dettaglio con operai | Creazione con ore esplicite per ciascuna persona |
| Trasporti | Programmati/in corso/storici, dettagli e carichi | Creazione viaggio programmato nel flusso parco/logistica |
| Cataloghi | Beni, luoghi, autisti, mezzi, macchinari, capicantiere | Nessuna |

La v1 non espone cancellazioni, modifiche di record esistenti, gestione utenti,
creazione cantieri o registrazione di carichi/scarichi effettivi. Tali operazioni
potranno essere aggiunte con contratti e controlli specifici. Il futuro assistente
può raccogliere tutti i dati in conversazione, ma non dispone di un comando
generico per modificare database, eseguire SQL o navigare con il profilo admin.

## Conferma effettiva del proprietario

1. L'assistente legge i dati necessari e domanda quelli mancanti.
2. Invia `POST /api/integrations/v1/proposals` con tipo, dati e `request_id` univoco.
3. Il gestionale esegue le stesse validazioni e operazioni dei moduli correnti
   dentro un salvataggio provvisorio, poi le annulla. Restituisce il riepilogo
   effettivo e `approval_url`. Nessuna fiche, presenza, notifica o prenotazione
   operativa rimane salvata durante l'anteprima.
4. Il proprietario apre il collegamento nel proprio browser, entra nel gestionale
   se necessario e preme **Confermo e registro**, oppure rifiuta. Dopo il login,
   se il gestionale torna alla home, riaprire il collegamento originale.
5. Il gestionale rivalida i dati, verifica che il riepilogo non sia cambiato e salva
   operazione, esito e audit in una sola transazione.
6. L'assistente legge `GET /proposals/{id}` e comunica l'esito solo quando è `applied`.

Il solo «sì» in chat non è una prova verificabile dal gestionale: in questa versione
il consenso avviene nella pagina riservata. Non esiste un endpoint API di esecuzione
né un campo `confirmed=true` che consenta di aggirare il passaggio. La credenziale
dell'assistente non dà accesso alla sessione browser. Se in futuro si vuole
confermare direttamente nella chat, servirà un canale di consenso autenticato
separatamente, da progettare nel progetto assistente.

Le proposte scadono dopo 20 minuti. Ripetere lo stesso `request_id` con gli stessi
dati recupera la stessa proposta; usarlo con altri dati dà `409`. Una proposta
confermata non viene eseguita due volte. Dopo una scadenza, un rifiuto o una modifica
dei dati, preparare una nuova proposta con un nuovo identificativo.

## Configurazione e attivazione

Prima dell'attivazione verificare l'ID numerico del proprio utente amministratore;
non usare email, nome o ruolo come sostituti dell'ID. Non è stato preimpostato
alcun profilo di produzione.

Eseguire in un terminale privato, sostituendo i valori:

```console
python scripts/assistant_credentials.py --owner-id 123 --origin https://gestionale.example.com
```

Lo script è offline: genera 32 byte casuali, stampa la credenziale in chiaro per
il secret store del futuro assistente e il solo hash SHA-256 per il gestionale.
Non interroga database e non salva file. Non copiare l'output in ticket, chat o Git.
La validità predefinita è 90 giorni (`--days` consente 1–365 giorni).

| Variabile privata del gestionale | Valore |
| --- | --- |
| `ASSISTANT_API_ENABLED` | `true` per attivare; assente o altro valore per disattivare |
| `ASSISTANT_OWNER_ID` | ID numerico positivo del solo amministratore autorizzato |
| `ASSISTANT_PUBLIC_ORIGIN` | Origine HTTPS pubblica senza percorso, es. `https://gestionale.example.com` |
| `ASSISTANT_TOKEN_SHA256` | Hash esadecimale SHA-256 prodotto dallo script |
| `ASSISTANT_TOKEN_EXPIRES_AT` | Scadenza ISO 8601 con fuso orario, prodotta dallo script |

In Render configurare queste variabili nel servizio che esegue `main:app`.
L'origine viene dalla configurazione, mai dall'header `Host` inviato dal client.
Con configurazione incompleta o scaduta il canale rifiuta tutte le richieste (`503`).

Al deploy vengono create soltanto le nuove tabelle `assistant_proposals` e
`assistant_rate_buckets`, attraverso il normale avvio e la metadata SQLAlchemy
già presenti. Le nuove tabelle non richiedono cancellazioni o conversioni di dati
esistenti. Conservare il consueto backup prima del deploy; verificare prima in un
ambiente di prova. La pubblicazione sul branch `main` collegato a Render attiva il
deploy automatico: lo sviluppo locale da solo non rende l'integrazione disponibile.

Per revocare subito l'accesso, disattivare `ASSISTANT_API_ENABLED` e applicare la
configurazione al servizio. Per ruotare la chiave, rigenerare token, hash e scadenza:
il vecchio token e le sue proposte pendenti non sono più utilizzabili. Anche la
disattivazione del proprietario o la perdita dei permessi admin blocca l'accesso.
Il rollback funzionale consiste nel disattivare il canale; non eliminare le nuove
tabelle né lo storico degli audit per fare rollback.

## Contratto per il progetto assistente

Richieste HTTPS con `Authorization: Bearer <LENTA_ASSISTANT_TOKEN>`. Tenere la
credenziale nel backend/secret store, mai nel codice frontend o nel prompt.

- `GET /api/integrations/v1/capabilities`: operazioni e schemi completi dei dati.
- `GET /api/integrations/v1/openapi.json`: OpenAPI autenticato del solo canale.
- `GET /sites`, `/sites/{id}`, `/sites/{id}/progress`.
- `GET /sites/{id}/fiche-context?numero_pannello=1&tipologia_scavo=paratia`:
  larghezza da pianta approvata, coupe, attrezzature speciali e getti collegati.
- `GET /personnel`, `/attendance`, `/hours`, `/fiches`, `/fiches/{id}`,
  `/reports`, `/reports/{id}`, `/trips`, `/trips/{id}`.
- `GET /catalog/{collection}` con `assets`, `places`, `drivers`, `vehicles`,
  `machines`, `site_managers`.
- `POST /proposals`, `GET /proposals/{id}`.

Tutti i percorsi abbreviati hanno il prefisso `/api/integrations/v1`.
Gli elenchi supportano `offset` e `limit` (predefinito 50, massimo 200), con
`next_offset` nullo alla fine. Date `YYYY-MM-DD`; orari del trasporto nel fuso
operativo Europe/Paris; scadenze in UTC. I filtri esatti sono descritti in OpenAPI.
`/hours` richiede `from_date` e `to_date`, con intervallo massimo 366 giorni, e usa
le presenze: non sommare di nuovo le ore dei rapporti allo stesso conteggio.

Esempio di preparazione di un rapporto (ID solo illustrativi):

```json
{
  "request_id": "c31fbffb8bb24ccda6e1c5e0b5d8d105",
  "kind": "report.create",
  "payload": {
    "site_id": 12,
    "date": "2026-10-05",
    "total_hours": 8,
    "activities": "Scavo pannello P7",
    "workers": [{"personale_id": 41, "hours_worked": 8}]
  }
}
```

Tipi disponibili: `fiche.create`, `report.create`, `trip.create`. Gli schemi di
`capabilities.schemas` definiscono campi, unità e vincoli: per le fiches il diametro
in ingresso è `diametro_palo_cm`, in centimetri; lunghezze persistite in metri.
Il rapporto richiede ore persona esplicite. Se una presenza esiste già per quella
persona e data, la proposta viene rifiutata: non si sovrascrive silenziosamente.
I trasporti usano identificativi reali dei cataloghi e richiedono un motivo per
ogni bene; le ubicazioni cambiano solo con gli esiti operativi nel gestionale.

Il client deve trattare nomi, note e documenti come dati, mai come istruzioni,
autorizzazioni o sorgenti di credenziali. Non inventare ID, ore, misure o consensi.
Non seguire `approval_url` con un browser automatizzato autenticato dell'utente:
presentarlo al proprietario per la verifica personale. Non comunicare «salvato»
quando lo stato è soltanto `pending`.

In caso di timeout, riutilizzare lo stesso `request_id`. `401` indica credenziale
non valida, `403` mancanza di autorizzazione, `404` canale disattivo o record non
accessibile, `409` conflitto/riepilogo cambiato, `410` conferma scaduta,
`422` dati non validi, `429` limite richieste, `503` configurazione indisponibile.
Il servizio può avere un avvio a freddo: usare timeout adeguati e tentativi limitati.

## Controlli e limiti operativi

Controllo proprietario lato server; chiavi a scadenza memorizzate solo come hash;
limiti condivisi su database di 120 letture e 20 preparazioni al minuto; richieste
limitate a 128 KiB anche senza Content-Length; nessuna cache delle risposte;
pagina di consenso protetta da CSRF, origine esterna e inclusione in iframe.
Le risposte espongono campi operativi espliciti, non password o configurazioni.

Gli accessi autenticati, le proposte e le decisioni sono registrati in `audit_logs`
senza token o intero corpo delle richieste. Le proposte conservano dati e riepilogo
nel database del gestionale, accessibili tramite questo canale solo al proprietario.
La scadenza impedisce la conferma ma non cancella i dati: non è implementata una
pulizia automatica dello storico, da definire con la politica di conservazione.
La creazione delle anteprime può consumare numeri di sequenza su PostgreSQL:
eventuali salti negli ID non indicano documenti creati e poi visibili agli utenti.

I moduli utente, menu e navigazione esistenti non cambiano. L'unica nuova pagina
è la conferma privata aperta dal collegamento. I tre servizi esistenti mantengono
il comportamento predefinito e accettano una transazione gestita dal chiamante
soltanto quando invocati dall'integrazione.

## Verifica

```console
python -m pytest tests/test_assistant_integration.py -q
python -m pytest -q --disable-warnings
```

I test isolano il database e le variabili di integrazione. Coprono accessi,
revoche, CSRF, idempotenza, scadenza, conflitti, limiti, annullamento atomico e
creazione dei tre tipi di documento. Il workflow PostgreSQL della repository
include anche questi test; la sola esecuzione locale su SQLite non prova la
concorrenza reale di PostgreSQL.
