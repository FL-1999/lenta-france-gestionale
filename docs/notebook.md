# Appunti e riunioni

## Uso

`/appunti` è il quaderno del profilo autenticato. È raggiungibile dal menu, da
Il mio spazio e dalle schede cantiere di manager e caposquadra. Il personale
trova il collegamento anche nell'assegnazione attuale al cantiere.
`/appunti?cantiere=ID` filtra lo stesso archivio, senza duplicare i documenti.

Ogni nuovo appunto è privato. Si possono scrivere appunti liberi, riunioni con
partecipanti/punti/decisioni/attività e liste, organizzati in raccolte personali.
Il cantiere è facoltativo: acquisti generali, riunioni interne e promemoria possono
rimanere senza cantiere anche dopo il riordino AI.
La selezione di un cantiere o di un partecipante non concede accesso. Nessun
ruolo applicativo, neppure admin, permette di leggere gli appunti altrui.

Solo il proprietario può scegliere account attivi e concedere lettura o
modifica, revocare, cambiare classificazione, archiviare e consultare le
versioni precedenti. Un destinatario con modifica vede e modifica la versione
condivisa, ma non le raccolte private, gli originali, le bozze AI o gli accessi.
La notifica di condivisione non contiene titolo/testo, per non lasciare estratti
dopo una revoca. La revoca impedisce le successive letture, ma non può cancellare
contenuti che un destinatario abbia già letto o copiato.

La modifica di un documento già condiviso aggiorna il contenuto per i destinatari
esistenti; il modulo lo indica prima di salvare. L'archiviazione conserva i permessi:
per togliere l'accesso usare **Rendi privato**. L'eliminazione del cantiere conserva
appunto, nome/codice del cantiere, originali e permessi nel quaderno personale.

## Riordino e verbale con AI

La funzione è un'elaborazione esplicita del solo appunto selezionato, disponibile
per il proprietario su un documento privato e non archiviato. La finestra di
conferma indica che testo e sezioni vengono inviati a OpenAI.

Configurazione server:

| Variabile | Significato |
|---|---|
| `NOTES_OPENAI_API_KEY` | Chiave OpenAI API riservata al server, inserita fra i segreti Render. Non è una chiave del gestionale. |
| `NOTES_AI_USER_IDS` | ID utenti autorizzati, separati da virgole. Se assente usa `ASSISTANT_OWNER_ID`. Per l'installazione del proprietario: `2`. |
| `NOTES_AI_MODEL` | Modello con Responses e Structured Outputs. Predefinito `gpt-4.1-mini`. |

In assenza di chiave o autorizzazione, scrittura/condivisione restano disponibili
e il pulsante spiega che il riordino è da attivare. Non vengono eseguite chiamate AI
all'apertura delle pagine o al salvataggio.

Il server chiama esclusivamente `https://api.openai.com/v1/responses`,
con `store: false`, schema JSON rigido, timeout e senza tool, ricerche o altri
documenti nel contesto. `store: false` disattiva l'archiviazione della Response;
non è una promessa di zero retention del provider. I limiti iniziali sono tre
richieste al minuto e trenta al giorno per utente (UTC), inclusi tentativi falliti.
I costi dipendono dal servizio API configurato.

La proposta non sovrascrive il testo: il proprietario controlla e sceglie
**Accetta bozza privata** oppure **Scarta proposta**. L'accettazione conserva
l'originale e non condivide. Modifiche, condivisioni o archiviazioni intervenute
durante la preparazione rendono la proposta precedente non applicabile.
Decisioni e attività sono sezioni del documento, non scritture su fiches,
rapportini, presenze, avanzamenti o attività del gestionale. Il modello può
sbagliare: nomi, misure e decisioni richiedono il controllo del proprietario.

## Riunioni con più cantieri

**Dividi per cantiere** prepara una proposta separata dal riordino. Il consenso
indica che, oltre al solo appunto selezionato, vengono inviati a OpenAI nomi,
codici e ID dei cantieri attualmente assegnabili dall'utente. Non vengono inviati
altri appunti, personale, documenti o dati operativi dei cantieri.

La proposta contiene al massimo 12 estratti per cantiere o senza cantiere per
punti generali, trasversali e riferimenti incerti. Un ID suggerito deve appartenere
al catalogo autorizzato e avere una citazione presente nell'appunto; questi controlli
non garantiscono l'attribuzione semantica, che il proprietario deve verificare.
Ogni estratto mostra il contenuto e un selettore di cantiere facoltativo.
Nessuna casella è preselezionata. **Crea gli appunti selezionati** crea solo
gli estratti selezionati; **Non dividere l'appunto** scarta la proposta.

Il verbale completo conserva testo, sezioni e classificazione. Gli estratti sono
sempre privati, ereditano solo la raccolta personale e hanno contenuto e accessi
indipendenti: modifiche successive non si sincronizzano. I collegamenti fra
verbale ed estratti sono visibili solo al proprietario, mai ai destinatari della
condivisione. Condividere un estratto non dà accesso al verbale o agli altri estratti.
La creazione è atomica e usa la versione del verbale; un retry della medesima
selezione restituisce il risultato esistente senza creare duplicati.

## Persistenza e sicurezza

Tabelle additive registrate nell'avvio ordinario di SQLAlchemy:
`notebook_notes`, `notebook_grants`, `notebook_revisions`, `notebook_drafts`,
`notebook_ai_quota`, `notebook_extracts`. Nessuna modifica distruttiva ai dati operativi.
Le richieste di scrittura usano CSRF firmato, controllo origine e versione
ottimistica del documento. Creazione e preparazione AI hanno chiavi idempotenti.
Ogni lista/lettura applica il filtro proprietario/destinatario prima dei filtri
di cantiere, ricerca o archivio. Tutti gli endpoint appunti restituiscono
`Cache-Control: private, no-store`; nessun testo viene salvato in localStorage
o nel service worker. Il contenuto è testo semplice, escapato nel browser.

Gli originali sono versioni complete prima delle modifiche. Le raccolte e la
rubrica delle condivisioni sono visibili solo al proprietario. L'audit registra
ID e variazioni dei permessi, mai il testo. Le note non vengono esportate
automaticamente nell'archivio documenti SharePoint né esposte tramite i tool
dell'assistente MCP. I backup tecnici completi del database le includono: i
controlli applicativi non escludono l'accesso degli operatori autorizzati al DB
o ai backup, come per gli altri dati riservati del gestionale.

Collaudi: `tests/test_notebook.py` (anche su PostgreSQL in CI) e
`tests/test_notebook_live.py` con `RUN_BROWSER_TESTS=1`. Tutti usano database
isolati; nessun test chiama OpenAI. Il collaudo browser copre 320/390 px,
desktop, condivisione/revoca, originali, accettazione della proposta e francese.
