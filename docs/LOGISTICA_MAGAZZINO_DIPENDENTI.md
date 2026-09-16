# Trasporti, magazzino e futura area dipendente

Analisi del gestionale interno e interventi del 16 settembre 2026. Il sito pubblico non rientra in questo intervento. Verifica effettuata sul codice e su database di collaudo; nessuna modifica alle giacenze o ai viaggi reali per fare le prove.

## Decisioni confermate

- Il magazziniere conferma la consegna/prelievo prima di scalare la giacenza. Una richiesta non equivale a materiale già uscito.
- Il dipendente vedrà le ore già registrate e il cantiere assegnato. Nessuna timbratura aggiuntiva.
- La classificazione definitiva dei materiali resta da definire con l’azienda. Non sono state inserite categorie o dotazioni inventate.
- Lo stile resta quello approvato: blu vetrato di notte, fondo grigio caldo di giorno, azioni principali rosse e divisioni con linea laterale.

## Valutazione

La base si può migliorare incrementalmente. Non serve rifare il gestionale. Esistono viaggi, tappe ordinate, autisti, QR delle attrezzature, richieste di magazzino, consegne parziali e storico dei movimenti. Il problema principale è collegare questi flussi senza confondere attrezzature riutilizzabili e materiali consumabili.

Non sarebbe corretto dichiarare oggi «tutto funzionante al 100%»: l’area dipendente, il prelievo tramite codice per tutti i ruoli e il collegamento fra i diversi cataloghi non esistono ancora come percorso completo. Questa analisi separa correzioni consegnate e lavoro restante.

| Asse | Esito |
|---|---|
| Tecnico | Buone basi di autorizzazione, transazioni e storico. Corrette destinazioni QR, registrazione degli scarichi e accessi concorrenti alle giacenze. Restano integrazioni fra cataloghi e prenotazioni. |
| UX/UI | Rifatti creazione e modifica veicolo. Scanner con operazione e tappe esplicite, codice digitabile e fotocamera su richiesta. La pianificazione richiede ancora di indicare i numeri delle tappe. |
| Business | Separazione fra richiesta, approvazione e consegna coerente con il lavoro del magazziniere. Occorre distinguere quantità fisica, prenotata e disponibile per evitare promesse di materiale già destinato altrove. |
| Visibilità | Per questo gestionale significa sapere dove sono mezzi/materiali, chi ha eseguito un movimento e cosa manca. Non SEO: i dati operativi restano riservati. |

## Cosa cambia adesso

### Veicoli

Creazione e modifica usano lo stesso modulo, organizzato in quattro contesti: identità; utilizzo/assegnazione; scadenze; note e GPS facoltativo. Etichette sopra ai campi, due colonne sul computer e una sul telefono. I valori già salvati vengono mantenuti, incluso il chilometraggio pari a zero. Corretto anche l’elenco: mostra il personale effettivamente assegnato e la disponibilità nei trasporti; la vecchia colonna cantiere leggeva proprietà assenti dal modello.

Il flag «Disponibile nella pianificazione trasporti» rende il mezzo selezionabile nei viaggi. Non certifica assenza di sovrapposizioni, portata sufficiente o validità delle scadenze. Il codice GPS da solo non attiva un servizio di tracciamento.

### Il tuo esempio: deposito → cantiere A → cantiere B

Imposta A come tappa 1, B come tappa 2 e destinazione finale. Ogni riga di attrezzature specifica tipo, quantità, punto di carico e tappa di consegna; il numero 0 indica l’origine del viaggio.

| Materiale d’esempio, non inventario aziendale | Quantità | Carico | Consegna |
|---|---:|---|---|
| Pompa | 1 | 0: deposito | 1: cantiere A |
| Altra attrezzatura | 1 | 1: cantiere A | 2: cantiere B |

1. Il manager pianifica il viaggio, assegna autista e mezzo e definisce le due righe.
2. Al deposito l’autista sceglie **Carica**, origine 0 e consegna A. Scansiona il QR della pompa o digita il codice stampato.
3. In A sceglie **Scarica**, tappa A, e conferma la pompa. Si aggiornano stato, posizione e storico.
4. Sempre in A sceglie **Carica**, origine 1 e consegna B, e conferma il codice della seconda attrezzatura.
5. In B conferma lo scarico. Lo storico riporta A → B, non deposito → B.
6. Aggiorna l’elenco prima della chiusura. Su un viaggio multitappa occorre confermare gli scarichi alle singole tappe oppure indicare esplicitamente ciò che resta sul camion.

Una scansione ripetuta della stessa operazione non genera un altro movimento. Una tappa appartenente a un altro viaggio è rifiutata. Una destinazione incompatibile con l’assegnazione è bloccata. Se esiste una lista pianificata, lo scanner verifica tipo, tratta e quantità prevista. I materiali in manutenzione, in uso o caricati su un altro viaggio non vengono caricati nuovamente.

Le tappe non valide o con buchi intermedi vengono rifiutate; la destinazione finale viene aggiunta se manca. I prelievi previsti alle tappe intermedie non vengono proposti come carico iniziale del deposito.

**Limiti residui:** una stessa attrezzatura può avere una sola assegnazione per viaggio: scaricarla in A e ricaricare *la stessa* per B richiede ancora un modello a più tratte per singolo bene. L’esempio con due attrezzature diverse è coperto. L’interfaccia di pianificazione mostra inizialmente tre righe/tappe; per itinerari più lunghi serve un editor con aggiunta/rimozione delle righe. Non sono introdotti ottimizzazione del percorso, controllo portata, prenotazione delle attrezzature o verifica fisica del luogo tramite GPS.

### Magazzino: come funziona realmente

Il catalogo comprende **macro → categoria → articolo**. L’articolo ha codice, unità di misura, giacenza, soglia minima e costo facoltativo. I movimenti registrano quantità, operatore e, quando disponibile, destinazione e richiesta/ordine collegato.

Il percorso esistente per il caposquadra è:

**Richiesta → approvazione del magazziniere/responsabile → consegna confermata → aggiornamento quantità e movimento.**

Esempio di collaudo: 10 pezzi a magazzino, richiesta di 4. Dopo richiesta: 10. Dopo approvazione: 10. Prima consegna di 2: 8, richiesta parziale. Consegna dei 2 rimanenti: 6, richiesta evasa. Ripetere l’evasione completa non scala nuovamente lo stock.

I responsabili possono anche effettuare carichi, scarichi e rettifiche diretti. I driver non ricevono per questo accesso alla gestione centrale del magazzino. La futura richiesta tramite codice dovrà passare dalla stessa conferma del magazziniere.

Correzioni aggiunte: quantità non numeriche/non finite rifiutate, virgola decimale riconosciuta, blocco di carichi/scarichi rapidi su articoli archiviati, protezione delle righe di giacenza durante operazioni concorrenti e protezione delle richieste durante evasione/approvazione. Una richiesta già parzialmente o completamente evasa non torna approvata con un altro clic. La consegna della richiesta richiama anche l’avviso di scorta bassa.

**Limiti residui:** la quantità disponibile dell’articolo è globale, non un saldo distinto per ogni deposito/cantiere. L’approvazione non prenota una quantità. Le operazioni parziali e gli scarichi liberi non hanno ancora un identificativo univoco della singola conferma: un secondo invio intenzionale di una quantità parziale può rappresentare un’altra consegna. Serve quindi una protezione dei reinvii prima di generalizzare il prelievo a tutti i dipendenti. Il codice articolo non ha un vincolo univoco nel database: occorre verificare e risolvere eventuali duplicati prima di utilizzarlo come chiave universale di scansione.

## Le integrazioni da progettare

### Un’identità unica per i beni riutilizzabili

Nel codice i QR stampabili sono nel catalogo `Attrezzatura`; lo scanner dei trasporti legge quell’archivio. `Machine`, usato anche dalle fiches e dalle assegnazioni ai cantieri, è separato. Non basta stampare un QR per affermare che i due sistemi siano collegati.

Proposta: collegamento esplicito e univoco fra macchina e attrezzatura trasportabile, mantenendo i dati tecnici e lo storico esistenti. La consegna confermata deve aggiornare anche l’assegnazione della macchina al cantiere. Prima del collegamento va verificato se lo stesso bene è già presente in entrambi gli archivi; nessun abbinamento automatico basato solo su un nome simile.

### Il prelievo tramite codice, per tutti i ruoli

Il futuro percorso condiviso per dipendente, caposquadra e autista dovrebbe essere:

**Leggi/digita codice → riconosci articolo → quantità e destinazione → invia richiesta → il magazziniere conferma quanto consegna → aggiorna giacenza e storico.**

La schermata deve mostrare chiaramente «In attesa di conferma»: nessun saldo definitivo prima della conferma. I consumabili vanno gestiti con quantità e unità; un bene identificato singolarmente con QR va movimentato come bene riutilizzabile. Sono necessari anche reso, rifiuto/correzione della richiesta, consegna parziale, autore e ora dell’operazione e protezione contro i doppi invii. Il driver deve poter collegare una richiesta alla tratta e alla tappa senza produrre un secondo scarico quando conferma la consegna del trasporto.

### Area dipendente essenziale

Non è stata aggiunta in questa consegna. La struttura consigliata è composta da:

- **La mia settimana:** lunedì–venerdì, sabato/domenica visibili quando hanno registrazioni; totale delle proprie ore registrate e dettaglio giornaliero. Le ore eventualmente in attesa di verifica devono essere riconoscibili.
- **Il mio cantiere:** luogo pianificato per la giornata, con indicazione chiara se manca un’assegnazione. Non dedurre automaticamente l’assegnazione futura dall’ultimo rapportino.
- **Le mie richieste:** codice, quantità richiesta, consegnata e stato; attivabile insieme al nuovo percorso magazzino.

Il collegamento deve usare `Personale.user_id`: un dipendente può leggere solo il proprio profilo, le proprie ore e le proprie richieste. Nessuna modifica di ore, dati di colleghi, salari, costi, catalogo, stock o pianificazione. Occorre introdurre un ruolo/permessi dedicati e migrare l’enumerazione PostgreSQL, senza attribuire per comodità il ruolo caposquadra. Non sommare presenze e rapportini se le prime derivano già dai secondi, altrimenti le ore vengono contate due volte.

## Priorità con evidenze

| Priorità / stato | Problema → evidenza → impatto → soluzione → beneficio → difficoltà |
|---|---|
| **CRITICAL — corretto** | Scarico QR senza storico → handler `driver_trasporti_viaggi_scan` aggiornava solo stato/posizione → tracciabilità incompleta → movimento registrato nella stessa transazione → consegna rintracciabile → media. |
| **CRITICAL — corretto nei percorsi modificati** | Aggiornamenti concorrenti dello stock → lettura/modifica/salvataggio senza blocco in `routes/magazzino.py`, con ingressi anche in `routes/ordini.py` → quantità perse o uscite sovrapposte → blocchi transazionali ordinati su richieste/ordini/articoli → saldo coerente fra operatori → media. |
| **HIGH VALUE — implementato per beni diversi** | QR assegnato alla prima tappa, origine sempre quella del viaggio → `routes/trasporti.py`, modelli di richiesta/assegnazione → consegna o storico errati → tratta di carico/consegna esplicita e validata → copertura deposito/A/B → media. |
| **HIGH VALUE — corretto** | Modulo veicolo con etichette/campi stretti e struttura duplicata → template new/edit, classe `form-grid-2` → compilazione faticosa → modulo condiviso e sezioni responsive → leggibilità e coerenza → bassa. |
| **HIGH VALUE — da implementare** | Macchina e attrezzatura sono identità separate → `Machine` e `Attrezzatura` in `models/entities.py` → posizione non sincronizzata → relazione univoca e aggiornamento delle assegnazioni → unica storia del bene → alta, con riconciliazione dati. |
| **HIGH VALUE — da implementare** | Driver/dipendente non hanno il prelievo condiviso tramite codice → controlli ruoli in `routes/magazzino.py`, ruolo dipendente assente → attività fuori sistema → richiesta personale con conferma e protezione reinvii → giacenze affidabili → alta. |
| **HIGH VALUE — da implementare** | Stock globale senza prenotazione → singolo `MagazzinoItem.quantita_disponibile` → più richieste approvate possono contendersi materiale → quantità fisica/prenotata/disponibile e saldi per luogo → pianificazione attendibile → alta. |
| **HIGH VALUE — da implementare** | Planner raggruppa per mezzo/giorno ma non valida sovrapposizioni temporali → `manager_trasporti_planner`, `manager_trasporti_viaggi_move_date` → doppio impegno di autista/mezzo possibile → intervalli temporali e avvisi di conflitto, con override motivato → programma realistico → media/alta. |
| **MEDIUM — da definire** | Classificazione non ancora concordata → macro/categorie esistono, tassonomia aziendale non fornita → catalogo incoerente → concordare famiglie, unità, codici e ubicazioni prima dell’import → ricerca rapida → media. |
| **LEAVE AS IS** | Tappe ordinate, QR individuali, ruoli separati, storico movimenti e consegne parziali → modelli e test esistenti → basi utili → conservarle e integrarle → meno rischi e nessuna riscrittura inutile → nessun intervento strutturale immediato. |

## Prove e limiti del collaudo

- `tests/test_logistics_workflows.py`: pianificazione attraverso HTTP, viaggio con due tappe e carico intermedio, scarico errato, scansioni ripetute, accesso da altro autista, storico di due consegne, chiusura viaggio, piano non valido, richiesta/approvazione/evasione parziale, quantità invalide e creazione/modifica veicolo.
- Stesso file: prova PostgreSQL con due transazioni indipendenti che chiedono 8 pezzi ciascuna su un saldo di 10; l’esito richiesto è una sola uscita, saldo 2. Non viene simulato il blocco con SQLite.
- `tests/test_logistics_live.py`: browser con login reale, salvataggio veicolo, giorno/notte, larghezza telefono, codice digitato, scarico e verifica del movimento nel database.
- `tests/test_mobile_browser.py`: eventi di lettura QR simulati per controllare doppia scansione e visualizzazione sicura dei nomi. La fotocamera fisica e le etichette reali devono ancora essere provate sul telefono dell’autista.
- Restano da verificare nell’ambiente operativo: catalogo reale e possibili duplicati, impostazioni del fornitore GPS, qualità/stato delle etichette QR, copertura di rete, persone associate agli account e procedure di consegna effettive.

## Dati utili per il passo successivo

Quando descriverai i materiali, bastano esempi reali di articoli e attrezzature con codice eventualmente già usato, unità (pezzi, metri, litri…), depositi/ubicazioni, distinzione consumabile/riutilizzabile e chi può confermare i prelievi. Servirà poi identificare quali macchinari hanno già una corrispondente attrezzatura con QR. Nessuna password o credenziale è necessaria in questo documento.

Raccomandazione: mantenere l’attuale gestionale, consolidare identità dei beni e movimenti di magazzino, poi aprire l’area personale ai dipendenti. Estendere prima i permessi senza queste basi renderebbe più difficile fidarsi delle giacenze.
