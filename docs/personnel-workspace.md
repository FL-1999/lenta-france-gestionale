# Personale, squadre e spazio personale

## Accesso e attivazione

- `/mio-spazio` è accessibile a tutti gli account attivi, con dati esclusivamente dell'anagrafica `Personale.user_id` collegata. Il nuovo ruolo `personale` apre direttamente questa pagina e non concede accesso a cantieri, fiches, trasporti o dati di colleghi.
- In **Personale → Modifica**, l’admin crea direttamente un accesso **Solo spazio personale** o **Caposquadra**, già collegato alla scheda esistente. Servono email e password iniziale (almeno 12 caratteri); non si crea una seconda anagrafica. Email già utilizzate richiedono il collegamento esplicito dell’account esistente. Il collegamento non ne modifica i permessi. Le operazioni sono atomiche, protette da CSRF, controllate sul server e tracciate senza password nello storico.
- L’admin può cambiare fra i due tipi di accesso dalla scheda; gli account con permessi specifici restano gestiti in **Utenti**. Prima di togliere il ruolo caposquadra occorre riassegnare cantieri e squadre attivi. La mansione aziendale resta separata dai permessi.
- **Includi nel registro presenze**, nella scheda e in **Presenze → Gestisci persone nel registro**, è una scelta per ogni persona, riservata all’admin. Il valore iniziale è incluso, anche per gli admin. L’esclusione filtra elenco settimanale, viste mensili e riepiloghi del registro: conserva account, ore, rapportini e storico. L’admin può consultare anche gli esclusi e reinserirli. Le ore personali e i documenti di origine non cambiano. Il campo `personale.incluso_presenze` viene aggiunto al database esistente con default vero tramite la migrazione portabile già usata dall’applicazione.
- I ruoli operativi esistenti conservano le proprie pagine e trovano **Il mio spazio** nel menu. Le fiches restano nelle funzioni del caposquadra e dell'ufficio.
- Admin e manager gestiscono comunicazioni, classificazioni e allegati. Il caposquadra vede soltanto la disponibilità dei componenti assegnati ai suoi cantieri.

## Flussi e fonti dei dati

- Le squadre associano un cantiere o deposito a un caposquadra. Le appartenenze hanno date di validità; assegnazioni sovrapposte vengono rifiutate. Il responsabile operativo del cantiere rimane `Site.caposquadra_id`.
- La pianificazione giornaliera esistente prevale sull'appartenenza abituale, per consentire spostamenti temporanei. Le assegnazioni non creano ore.
- **Carica la squadra prevista** nel rapportino propone i presenti. Si possono escludere persone, segnalare l'assenza all'ufficio o scegliere sostituti nelle righe ordinarie. La composizione abituale rimane invariata. La schermata mantiene il limite esistente di 10 persone, caposquadra incluso.
- Le ore personali leggono `PersonalePresenza`, la stessa fonte del registro. Le richieste di correzione non modificano ore; l'ufficio corregge il documento di origine e risponde.
- Ferie: richiesta in attesa, esito dell'ufficio, eventuale classificazione. Non esistono saldi, maturazioni o disponibilità ferie.
- Assenza: segnalazione immediata, presa in carico e classificazione dell'ufficio. Una data finale sconosciuta segnala indisponibilità senza generare presenze future indefinite. Completando data finale e classificazione si registrano i giorni.
- La registrazione ordinaria riguarda lunedì–venerdì; l'ufficio può includere sabato e domenica. Le voci comprendono ferie/congé payé, congé sans solde, malattia, permesso e altra assenza.
- Le presenze create da una comunicazione sono tracciate separatamente. Cambiare o annullare un esito modifica soltanto tali presenze, verificando che non siano state modificate altrove. Altri dati producono un conflitto. L'ufficio può rimuovere una registrazione manuale errata con conferma esplicita e controllo della versione; un rapportino va corretto alla fonte. Ogni operazione rimane nello storico.

## Allegati e notifiche

Certificati facoltativi PDF, JPEG e PNG, massimo 5 MB, conservati cifrati nel database. Non sono salvati in percorsi statici, notifiche o risposte della squadra. Il download autenticato è riservato al titolare e all'ufficio, con `Content-Disposition: attachment` e `Cache-Control: private, no-store`. La chiave Fernet è derivata da `SECRET_KEY` con separazione di dominio: una rotazione della chiave richiede di ricifrare gli allegati prima di rimuovere la vecchia chiave. I backup devono conservare database e segreto applicativo separatamente.

La postilla sulla consegna dell'originale descrive la procedura aziendale richiesta. L'ufficio può annotarne la ricezione. Le notifiche esistenti segnalano nuove comunicazioni, esiti e assegnazioni senza dettagli medici.

## Consultazione da telefono

Sotto 768 px l’elenco Personale mostra una scheda per persona con contatti, mansione, stato e azioni leggibili, senza scorrimento laterale. Il registro settimanale raggruppa i giorni sotto il nome: toccando un giorno il modulo di modifica si allarga all’intera scheda. I comandi per copiare lunedì, consultare rapportini e comunicazioni e salvare le presenze conservano i permessi e le regole precedenti. Il filtro **Persona** consente di restringere la consultazione e resta applicato dopo il salvataggio; non modifica l’inclusione nel registro, riservata all’admin.

Su PC rimane la tabella. Le prove di leggibilità coprono 320/390 px, italiano/francese, tema scuro, filtro e salvataggio di una presenza reale nel database isolato (`tests/test_mobile_readability_browser.py`). Le sezioni dei moduli fiche si dispongono in colonna sul telefono; le schede tecniche di stampa mantengono la loro impaginazione.

## Schema e verifica

Nuove tabelle additive `personnel_*`, nessuna riscrittura di presenze storiche o assegnazione automatica di account in produzione. Lo startup aggiunge in modo idempotente il valore PostgreSQL `roleenum.personale` prima di usare il nuovo ruolo. SQLite utilizza i modelli aggiornati.

Test funzionali: `tests/test_personnel_workspace.py`, incluso nella suite PostgreSQL. Test browser: `RUN_BROWSER_TESTS=1 python -m pytest tests/test_personnel_browser.py`; utilizza un server locale, credenziali di collaudo e un database temporaneo. Copre login personale, richiesta/approvazione, registro condiviso, rapportino dalla squadra e layout 320/390 px.
