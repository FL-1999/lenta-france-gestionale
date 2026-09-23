# Lenta France — attivazione SharePoint

## Stato e confini

Il gestionale è predisposto; un sito SharePoint vuoto NON è ancora un collegamento attivo.
Sito documenti previsto: https://lentafrance.sharepoint.com/sites/gestionale-app
La raccolta visualizzata come «Documenti» può avere un nome interno diverso: usare il drive ID, non dedurlo dall'etichetta.

| Contenuto | Archivio operativo | Copia SharePoint |
| --- | --- | --- |
| Articoli, quantità, codici fornitori, ordini, bolle e movimenti | Database | Backup nativo del database |
| Cantieri, coupe, fiches, getti, quote, pannelli e geometrie della pianta | Database | Backup nativo del database |
| PDF originali delle piante, anteprime, documenti e foto caricati nei cantieri | Database | File nella raccolta documenti |
| Fatture allegate | Database, con download autenticato | File nella raccolta documenti |
| PDF di fiche, dossier e report produzione | Acquisiti nel database quando esportati | File nella raccolta documenti |
| Fiches mai esportate e riepiloghi CSV/HTML | Dati nel database; documento rigenerabile | Dati inclusi nel backup; nessun PDF inventato |
| Codice applicazione e loghi statici | Repository Git | Non inclusi nel backup del database |
| Credenziali e configurazione Render | Variabili protette del server | Non inserite nei documenti né nei backup |

La coda conserva copie indipendenti degli originali e delle revisioni acquisite. Il titolare può escluderle dal trasferimento, spostarle nel cestino privato, recuperarle o eliminarle definitivamente con conferma esplicita. Non è un cestino completo dei record: recuperare un documento non ripristina automaticamente un cantiere o i suoi collegamenti. Nessuna scadenza o pulizia automatica è attiva.

## 1. Attività dell'amministratore Microsoft

1. Registrare in Microsoft Entra un'applicazione single-tenant per il backend Lenta France.
2. Autorizzazione **Microsoft Graph / Application / Sites.Selected**, con consenso amministrativo.
3. Con un'identità amministrativa separata, assegnare all'app il ruolo `write` SOLO sul sito scelto. Il consenso a Sites.Selected da solo non dà accesso. Non dare all'app permessi globali su tutti i siti.
4. Recuperare tenant ID, application/client ID, site ID e drive ID. Le credenziali vanno inserite direttamente nelle variabili protette Render; non in chat, ticket, Git o schermate del gestionale. Questo adattatore usa un client secret: annotarne scadenza, responsabile e rinnovo.
5. Creare una **destinazione backup separata**, preferibilmente un secondo sito SharePoint riservato al titolare. Assegnare l'accesso all'app anche a quel sito. Il nome “Backup” non rende privata una cartella. Verificare concretamente che i dipendenti non possano leggerla. Gli amministratori Microsoft restano soggetti ai privilegi del tenant: non promettere invisibilità assoluta rispetto a loro.
6. Verificare licenze esistenti, quota libera, versionamento, condivisione e politiche di conservazione. Non acquistare capacità aggiuntiva prima della verifica.

Endpoint di individuazione (da eseguire con autorizzazioni appropriate):

```text
GET https://graph.microsoft.com/v1.0/sites/lentafrance.sharepoint.com:/sites/gestionale-app
GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions
{"roles":["write"],"grantedToIdentities":[{"application":{"id":"<client-id>","displayName":"Lenta France Gestionale"}}]}
```

L'app ordinaria non si assegna autonomamente i permessi. Il tecnico usa i propri strumenti amministrativi per il grant iniziale.

## 2. Variabili Render

```dotenv
SHAREPOINT_HOSTNAME=lentafrance.sharepoint.com
SHAREPOINT_TENANT_ID=<tenant-guid>
SHAREPOINT_CLIENT_ID=<application-guid>
SHAREPOINT_CLIENT_SECRET=<inserire solo nel pannello protetto Render>
SHAREPOINT_SITE_ID=<site-id restituito da Graph>
SHAREPOINT_DRIVE_ID=<drive-id raccolta Documenti>
SHAREPOINT_SYNC_ENABLED=false
CLOUD_ARCHIVE_OWNER_EMAIL=federico.lenta@lentafrance.com

# Solo dopo avere verificato realmente gli accessi della destinazione privata:
SHAREPOINT_BACKUP_SITE_ID=<site-id destinazione privata>
SHAREPOINT_BACKUP_DRIVE_ID=<drive-id diverso dalla raccolta documenti>
SHAREPOINT_BACKUP_ACCESS_CONFIRMED=false
```

Il titolare configurato deve essere anche admin del gestionale. L'archivio documentale scaricabile è negato agli altri account anche se admin. La pagina di collegamento e i suoi controlli restano accessibili agli admin. I normali allegati degli ordini mantengono le autorizzazioni ordini.

## 3. Primo avvio e documenti precedenti

1. Al primo avvio viene eseguita un'acquisizione iniziale in background, anche senza credenziali Microsoft. Nel gestionale: **Generali → SharePoint → Prepara documenti esistenti** permette di ripeterla: lo stesso documento non si duplica.
2. Controllare gli allegati non acquisiti. Le vecchie fatture erano su `static/uploads/invoices`: se il file è già scomparso dal disco Render, serve recuperarlo da un'altra copia. I vecchi allegati superiori a 64 MB richiedono una migrazione dedicata per non saturare la memoria del servizio. Non vengono segnalati come trasferiti. Fare la prima acquisizione prima di qualsiasi pulizia dei vecchi dischi.
3. Configurare gli accessi sul server, mantenendo la sincronizzazione disattivata. **Verifica collegamento** controlla sito e raccolta in lettura; non prova ancora la scrittura.
4. Prima di attivare il trasferimento, il titolare seleziona i file di prova e usa **Escludi dal trasferimento** oppure **Sposta nel cestino**. PDF e anteprima sono copie distinte. Poi impostare `SHAREPOINT_SYNC_ENABLED=true` e riavviare il servizio. Il worker esamina solo la coda attiva ogni 60 secondi, al massimo 3 file per ciclo. I file nuovi vengono acquisiti anche prima dell'attivazione.
5. Controllare una prima copia con stato **Verificata**. Il file remoto viene riletto e confrontato byte per byte tramite SHA-256 e dimensione. Permessi insufficienti, quota, rete o contenuto difforme producono un errore e un nuovo tentativo; la copia locale rimane.
6. Verificare che un allegato si apra ancora nel gestionale durante un'interruzione del cloud. L'app continua a leggere la copia locale.

Cartelle create automaticamente: `Gestionale/Cantieri/cantiere-ID/Documenti`, `Piante-originali`, `Piante-anteprime`, `Fiches`, `Dossier`; fatture senza cantiere in `Gestionale/Acquisti/Fatture`. I nomi file includono ID e hash per evitare sovrascritture. Le modifiche apportate direttamente in SharePoint NON riscrivono i dati nel gestionale.

Per elaborare un arretrato dal server, con le stesse variabili e lo stesso database:

```sh
python -m scripts.sharepoint_sync --limit 100
```

I file già verificati non vengono copiati di nuovo. Se si cambia raccolta dopo l'attivazione, le copie precedenti mantengono la destinazione registrata: pianificare una migrazione specifica, non assumere che il cambio di variabile sposti l'archivio.

## Archivio, esclusioni e cestino privato

Solo l'admin identificato da `CLOUD_ARCHIVE_OWNER_EMAIL` può modificare il ciclo di vita delle copie, aprire il cestino o scaricare copie di recupero. Gli altri admin mantengono i controlli di connessione e inventario.

Le copie mostrano nome e numero del cantiere, data di caricamento dell'originale (UTC), numero del disegno e collegamento per aprire esattamente quella pianta. PDF e anteprima condividono numero ed etichette. **Pianta attualmente in uso** segue la scelta predefinita del cantiere: ultima pianta convalidata, oppure ultima bozza se non esistono piante convalidate. **Ultimo PDF caricato** identifica invece l'importazione più recente, anche se ancora in bozza o successivamente rimossa. Le due indicazioni possono quindi riguardare disegni diversi. Se cantiere/originale non esistono più, la pagina lo segnala; quando la data originale non è più disponibile mostra **Archiviato il**, senza dedurre una data di caricamento. Le medesime informazioni e un avviso per la pianta in uso compaiono nel riepilogo di eliminazione definitiva.

- **Escludi dal trasferimento** conserva la copia locale e sospende l'invio. Non rimuove una copia già trasferita. La nuova acquisizione degli stessi originali non annulla l'esclusione.
- **Sposta nel cestino** nasconde la copia dalle viste ordinarie e la esclude dalla coda. Non cancella ancora nulla da SharePoint. Non esistono scadenze automatiche.
- **Recupera tra gli esclusi** rende nuovamente disponibile il file senza avviare trasferimenti. **Includi nel trasferimento** lo rimette in coda, attiva solo se `SHAREPOINT_SYNC_ENABLED=true`. Il download recupera il file; non ricrea i dati applicativi.
- **Elimina definitivamente…** è disponibile dal cestino, anche con sincronizzazione disattivata. Mostra i file selezionati e richiede di digitare `ELIMINA DEFINITIVAMENTE` (oppure `SUPPRIMER DÉFINITIVEMENT`). Prima elimina il file remoto collegato mediante Graph `permanentDelete`, dopo verifica del contenuto; solo se riesce rimuove il payload locale. Un fallimento conserva il payload e mostra l'errore nel cestino. Non viene eseguito un normale DELETE remoto, che sposterebbe soltanto il file nel cestino SharePoint.
- Se un ID remoto già registrato non esiste più, la rimozione resta bloccata: potrebbe trovarsi nel cestino SharePoint. Se un upload mai verificato non ha prodotto un file nel percorso registrato, la copia locale può essere eliminata. Un vecchio tentativo senza destinazione registrata richiede verifica manuale.
- Originali ancora nei cantieri, vecchi backup, versioni soggette a conservazione Microsoft e copie scollegate/già nel cestino remoto non vengono cancellati. Una fattura che usa la copia come originale è protetta finché resta collegata a un ordine. Gli archivi eliminati mantengono un identificatore/hash senza contenuto per impedire la ricreazione da inventario; un nuovo caricamento esplicito della stessa fattura può creare nuovamente la copia operativa.
- Le azioni sono registrate nel registro audit. Un trasferimento in corso blocca le modifiche concorrenti; gli errori di eliminazione non vengono elaborati dal worker di upload. Se cambia raccolta, la rimozione è bloccata anziché cercare di eliminare nella destinazione nuova.

Verificare con un file di prova la disponibilità effettiva di `permanentDelete` con i permessi e le politiche del tenant. Se Microsoft rifiuta, la copia resta recuperabile; il gestionale non amplia autonomamente i permessi dell'applicazione.

## 4. Backup del database

Controllare prima dove punta realmente `DATABASE_URL`, senza copiarlo nei log. Non dedurre il provider dal codice. I backup del provider e la loro conservazione devono essere verificati separatamente.

- PostgreSQL: installare sul processo di backup `pg_dump` con versione compatibile con il server. Se manca, il gestionale lo segnala; nessun falso successo. Il dump nativo include tutte le tabelle, relazioni, blob e copie acquisite delle fatture.
- SQLite: il processo deve vedere il medesimo disco persistente e database. Non usare un job separato con un SQLite vuoto o un disco differente.
- Configurare la raccolta privata, poi `SHAREPOINT_BACKUP_ACCESS_CONFIRMED=true`.
- Eseguire una prima copia manuale dal server:

```sh
python -m scripts.sharepoint_sync --backup --limit 100
```

Il comando inventaria gli allegati, crea un backup nativo coerente, lo comprime con un manifesto, lo carica nella raccolta separata e ne verifica l'hash. Non salva il file di backup dentro il database stesso. I file temporanei vengono rimossi dopo l'esecuzione. Allegati precedenti mancanti bloccano la dichiarazione di backup completo. Un fallimento restituisce un codice di uscita diverso da zero.

Pianificare il comando sul server/job almeno ogni notte e concordare con il titolare quante ore di lavoro è accettabile perdere. La configurazione della pianificazione NON è automatica in questa release. Per PostgreSQL un job Render può usare lo stesso database e segreti; verificare costo e disponibilità di `pg_dump`. Attivare notifiche di errore del job e controllare lo storico in **SharePoint**. Conservazione iniziale senza eliminazioni: definire una durata dopo avere stimato lo spazio.

Le copie locali dell'archivio aumentano lo spazio del database (oltre agli originali già presenti): è una scelta temporanea di conservazione prudente. Misurare la crescita prima di attivare un'eventuale migrazione con eliminazione dei blob; questa release non la esegue. Mantenere una copia indipendente dal solo tenant Microsoft secondo il piano di backup aziendale.

## 5. Prova di ripristino obbligatoria prima di considerare conclusa l'attivazione

1. Scaricare un ZIP dalla raccolta privata e verificare SHA-256 rispetto allo storico.
2. Estrarlo in un ambiente isolato. Non sovrascrivere mai il database di produzione per fare una prova.
3. PostgreSQL: ripristinare `database.dump` con `pg_restore --no-owner --no-acl` in un database vuoto dedicato. SQLite: aprire la copia `database.sqlite3`, eseguire `PRAGMA integrity_check`, poi usare una copia per l'app di collaudo.
4. Avviare la stessa revisione del gestionale, con credenziali e configurazione protette fornite separatamente. Tenere la sincronizzazione SharePoint disattivata nell'ambiente di collaudo.
5. Verificare almeno un articolo e la sua giacenza, un ordine con fattura, un cantiere con pianta originale e pannelli, una coupe e una fiche con relativo PDF. Verificare gli account e le autorizzazioni.
6. Registrare data, responsabile, esito e tempo di recupero. Lo stato “copia verificata” prova il trasferimento, non questa procedura.

Non è possibile garantire perdita zero: database, allegati, frequenza dei backup e prove di recupero vanno valutati insieme.

## Documentazione ufficiale

- [Microsoft: permessi selettivi](https://learn.microsoft.com/en-us/graph/permissions-selected-overview)
- [Microsoft: autenticazione applicativa](https://learn.microsoft.com/en-us/graph/auth-v2-service)
- [Microsoft: upload session e blocchi](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0)
- [Microsoft: download e URL temporanei](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
- [Microsoft: eliminazione definitiva di un file](https://learn.microsoft.com/en-us/graph/api/driveitem-permanentdelete?view=graph-rest-1.0)
- [Render: dischi persistenti](https://render.com/docs/disks)
