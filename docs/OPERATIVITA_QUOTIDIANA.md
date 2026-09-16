# Operatività quotidiana — guida alle nuove funzioni

Questo pacchetto riguarda il gestionale interno. Le cinque aree proposte hanno una prima implementazione integrata, con limiti espliciti riportati sotto. La pubblicazione su Render avviene solo quando la richiesta GitHub viene unita a main.

## Dove trovare le funzioni

Dalla dashboard manager o caposquadra, aprire **Oggi: attività e verifiche**. Gli stessi collegamenti sono nel menu account, accessibile anche da telefono. **Pianificazione** apre la settimana corrente.

### Oggi

- Attività con scadenza entro oggi, collegate al cantiere.
- Rapportini da verificare per manager/admin; correzioni richieste sui propri rapportini per il caposquadra. Sono mostrati gli ultimi 30, con collegamento all'elenco completo.
- Cantieri visibili senza un rapportino di oggi. È un promemoria neutro, non un ritardo: non è stato inventato un calendario lavorativo aziendale.
- Richieste di magazzino in attesa/parziali e viaggi aperti previsti entro oggi per manager/admin.
- Revisioni correnti dei documenti scadute o in scadenza entro 30 giorni, se la data è stata indicata.

La data della nuova pagina segue il fuso Europe/Paris, incluso il cambio ora legale. I contatori non certificano che un cantiere dovesse lavorare in quel giorno.

### Bozza personale del rapportino

Le modifiche vengono salvate sul server dopo una breve pausa di digitazione. Il messaggio indica se la bozza è stata salvata, ripristinata oppure se il salvataggio non è riuscito. Riaprendo la pagina con lo stesso account si riprende la bozza. Ogni account ha una bozza corrente.

La bozza non crea ore, presenze o un rapportino ufficiale. L'invio crea il rapportino e chiude la bozza nella stessa transazione. Il token di revisione evita sovrascritture da schede aperte contemporaneamente e permette di riconoscere i tentativi ripetuti dello stesso invio. Il pulsante di invio viene bloccato mentre la richiesta è in corso.

**Copia il mio ultimo rapportino del cantiere** recupera attività, note, macchine e squadra dell'ultimo proprio rapportino precedente alla data scelta. Data e cantiere restano quelli selezionati. Confermare persone, ore e attività prima dell'invio; lavoratori non più disponibili richiedono una nuova selezione.

Limite: non è una modalità offline completa. Senza rete la bozza non raggiunge il server; il messaggio lo segnala e il browser avvisa prima di uscire con modifiche non salvate. Non viene promesso il recupero di modifiche perse chiudendo il dispositivo senza connessione.

### Verifica dei rapportini

Dal dettaglio o dall'elenco del caposquadra aprire **Verifica e correzioni**.

- I rapportini inviati sono **Inviati / da verificare**, compresi quelli storici che non hanno ancora una verifica registrata.
- Manager e admin possono **Validare** oppure **Richiedere correzione**, indicando una motivazione.
- Un rapporto validato non può essere modificato o eliminato senza essere prima riaperto per correzione.
- L'autore può modificare attività, note, macchinari e ore delle persone presenti, quindi **Rinviare alla verifica**.
- Lo storico registra autore, data, stato e nota della verifica. Gli orari dello storico sono indicati in UTC.

La modifica delle ore riutilizza le righe esistenti del personale. Lo stato nel grafico manager ora deriva dalla verifica, non dalla semplice presenza di ore.

Limite: i riepiloghi di produzione, presenze ed economia mantengono il criterio precedente e non escludono automaticamente i rapportini non validati. La validazione aggiunge un controllo operativo; un cambio delle regole contabili richiede una scelta esplicita.

### Pianificazione settimanale

Manager e admin possono assegnare persone, macchine e attrezzature a un cantiere attivo per un giorno. Il sistema impedisce due assegnazioni della stessa risorsa nello stesso giorno. Le rimozioni sono tracciate nell'audit. Il caposquadra vede le assegnazioni dei suoi cantieri.

Le assegnazioni coprono **la giornata intera** e non modificano presenze effettive, ore o posizione delle attrezzature. I trasporti della settimana sono mostrati accanto alla pianificazione e restano gestiti dal modulo Trasporti.

Limiti: non sono implementate assegnazioni a ore, suddivisione della giornata tra cantieri o verifica automatica dei conflitti tra tutti i moduli. Un mezzo elencato non è certificato come disponibile o idoneo: le informazioni operative rimangono da verificare.

### Revisioni dei documenti

Nell'elenco documenti del cantiere premere **Revisioni**. La prima versione resta l'originale; ogni caricamento successivo riceve un numero progressivo. È possibile indicare una scadenza, solo quando applicabile. La pagina evidenzia la revisione corrente e conserva i download delle precedenti.

Un caricamento partito da una pagina superata viene respinto se nel frattempo è arrivata una revisione più recente. Il vecchio comando Elimina non può cancellare un documento appartenente a una serie di revisioni, così non spezza lo storico.

Limiti: massimo 20 MB per nuova revisione; nessuna firma digitale o validazione tecnica del contenuto; l'indicazione Corrente significa ultima revisione caricata, non approvazione progettuale. La scadenza si imposta caricando una revisione.

## Collaudo e pubblicazione

La richiesta include test API per riservatezza delle bozze, versioni concorrenti, invio ripetuto, verifica e blocco dei rapportini, assegnazioni duplicate, documenti e visibilità per ruolo. Un test nel browser compila, salva, ricarica e invia la bozza a larghezza mobile. GitHub Actions esegue la suite su Linux/Chromium e le prove operative su un PostgreSQL di test separato.

Il collaudo aggiuntivo avvia anche un server reale su un database SQLite temporaneo, inizialmente privo delle cinque nuove tabelle. Usa login e sessioni distinti per manager e caposquadra, senza sostituire l'autenticazione: ripristina e invia una bozza, richiede e salva una correzione, rinvia e valida il rapporto, assegna persona e macchina, verifica il blocco del conflitto e scarica originale e nuova revisione. Controlla inoltre la pagina Oggi su desktop e telefono. Questa prova ha rilevato e permesso di correggere un conflitto JavaScript tra l'indirizzo del modulo e i pulsanti di verifica chiamati action. Il test resta nella suite per evitare che il difetto ricompaia. Non verifica il backup o la configurazione del database di produzione.

Le funzioni aggiungono cinque tabelle (report_drafts, report_reviews, report_review_events, resource_plans, document_versions). Le tabelle vengono create dall'inizializzazione già presente. Nessuna conversione o riscrittura dei rapportini, presenze e documenti precedenti è prevista. È aggiunta la dipendenza tzdata per rendere il fuso francese disponibile anche su Windows.

**Prima del merge:** verificare un backup ripristinabile di database e documenti e la persistenza dei dati su Render. Questi elementi di produzione non sono stati controllati tramite il repository. Provare le nuove funzioni in un ambiente di collaudo con dati separati. Non usare un database reale per i test automatici.

Con Render su main e Auto-Deploy On Commit, unire la richiesta GitHub avvia la pubblicazione. Dopo l'aggiornamento verificare login, Oggi, bozza, un rapporto di prova, un'assegnazione e una revisione documentale. La guida precedente CODEX_CORREZIONI_E_PUBBLICAZIONE.md descrive deploy e rollback.

Un rollback del codice non annulla i dati nuovi. Inoltre il vecchio codice non conosce il blocco dei rapportini validati: in caso di rollback, sospendere le modifiche a questi rapportini finché la protezione non è ripristinata. Non cancellare le nuove tabelle per tornare indietro.

## Da confermare per la fase successiva

Calendario lavorativo effettivo e festività; eventuale pianificazione a ore; regole sui rapportini validati da includere nei riepiloghi; politiche di conservazione e approvazione documenti; fornitore del database e procedura di ripristino. GPS reale e sito pubblico restano progetti distinti.
