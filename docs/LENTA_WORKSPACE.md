# Lenta Workspace — interfaccia condivisa

## Cosa cambia per chi usa il gestionale

- Su computer il menu è a sinistra. Ogni ruolo vede le proprie sezioni.
- Su telefono i collegamenti più frequenti sono in basso; **Menu** apre l’elenco completo. Il menu si chiude con la X, toccando lo sfondo o con Escape.
- Account, cambio ruolo, notifiche, lingua e tema restano nella barra superiore.
- La dashboard manager raggruppa rapportini, fiches e cantieri. **Nuovo rapportino** è l’azione principale; **Oggi** raccoglie attività e verifiche.
- Colori, pulsanti, moduli, tabelle e messaggi condividono lo stesso stile nelle aree manager, admin, caposquadra, autista, magazzino e ferraiolo.
- Il tema chiaro/scuro resta memorizzato sul dispositivo. Funziona anche quando il browser impedisce la memorizzazione locale, senza persistenza in quel caso.
- Il caposquadra può aprire **Fiches**: elenco paginato delle schede dei soli cantieri assegnati, con collegamento al cantiere. Ripara un collegamento già presente che non aveva una pagina di destinazione.
- Riparato il collegamento all’esportazione CSV che impediva l’apertura della reportistica avanzata.

## Dopo l’aggiornamento

Aprire il gestionale come sempre e aggiornare la pagina. Su Windows, se si vede ancora la vecchia grafica, usare **Ctrl + F5**. Su telefono chiudere e riaprire la pagina o l’app installata, con connessione disponibile.

Non servono nuove credenziali, inserimenti manuali dei dati, modifiche a Render o migrazioni del database per questo aggiornamento.

## Implementazione

`templates/shared/base.html` è il layout unico; `templates/base.html` è un alias che mantiene l’ereditarietà dei blocchi. Il menu laterale usa i permessi del ruolo attivo. Le regole di autorizzazione delle operazioni rimangono sul server.

`static/css/workspace.css` è caricato dopo il foglio storico. Definisce colori, tipografia, componenti e navigazione, mantenendo le geometrie specializzate di schede tecniche, mappe e disegni. I template autonomi per PDF produzione ed etichette QR non sono stati ridisegnati. In stampa il nuovo menu e le barre sono nascosti.

`static/js/workspace.js` gestisce menu, focus, account e contenitori delle tabelle; non salva dati aziendali. La versione del service worker cambia per rinnovare le risorse statiche.

## Collaudo riproducibile

Eseguire `RUN_BROWSER_TESTS=1 python -m pytest -q --disable-warnings`; su Windows con Edge disponibile impostare anche `PLAYWRIGHT_BROWSER_CHANNEL=msedge`.

- Accesso HTTP reale con password e cookie su un database temporaneo per tutti i sei ruoli.
- Controllo di tutti i collegamenti del menu per ruolo, rifiuto dell’area manager per autista, cambio ruolo admin → autista e logout.
- Tema chiaro/scuro e persistenza, lingua francese, apertura/chiusura/focus del menu a 320 e 390 px; passaggio fra desktop a 1440/1024 px e telefono.
- Visita di moduli e archivi rappresentativi: rapportini, fiches, cantieri, viaggi e carico, richieste magazzino, trasporti, gabbie, utenti. Controllo dei campi fuori schermo e degli errori JavaScript/server.
- Test dedicati all’isolamento dell’elenco fiches per cantiere assegnato, paginazione e rifiuto degli altri ruoli.
- Suite precedente di regressione: salvataggio e ripristino bozza, invio/correzione/validazione rapportino, pianificazione, revisioni documentali, permessi e scansione QR.

Gli screenshot di collaudo usano dati fittizi. Le prove del browser isolano i servizi esterni: non certificano Google Maps, la telecamera fisica, il GPS reale o tutte le combinazioni di dati presenti in produzione. Il controllo visivo riguarda schermate rappresentative; lo stile comune si estende alle altre pagine tramite il layout condiviso.

## Pubblicazione e ritorno alla versione precedente

La pubblicazione segue il collegamento esistente GitHub `main` → Render. Attendere i controlli della pull request prima del merge; poi verificare che Render serva il nuovo foglio `workspace.css` e il layout aggiornato sul login.

In caso di problema, ripristinare il commit precedente tramite un revert della pull request e lasciare che Render lo ripubblichi. Questo aggiornamento non modifica lo schema del database.
