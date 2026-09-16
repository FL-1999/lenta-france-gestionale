# Interfaccia condivisa: blu vetro e giorno minerale

Lo stile approvato usa il blu notte della proposta B e il grigio caldo della
proposta C di giorno. Le azioni principali sono rosse. I contesti hanno una
linea laterale azzurra di notte e blu minerale di giorno; il blocco Oggi ha la
linea rossa. I colori di stato continuano a distinguere errori, avvisi e successi.

## Organizzazione

- Manager e amministratore: Cantieri e lavoro; Logistica e risorse; Persone e
  squadre; Controllo operativo. Le card e i loro collegamenti restano disponibili.
- Caposquadra: Cantieri e lavoro; Materiali e attrezzature; Riepilogo della squadra.
- Autista: viaggio e percorso; carico e materiali; scanner e attrezzature a bordo;
  partenza e fine viaggio. Viaggi assegnati e disponibili restano separati.
- Magazzino: scorte e richieste, consumi, accessi alle operazioni.
- Ferraiolo: cantieri assegnati, riepilogo, paratie e pali. I colori degli stati
  delle gabbie restano distinti dal tema decorativo.
- Elenchi, dettagli e moduli: si riutilizzano le sezioni semantiche esistenti
  (filtri, risultati, dati base, attività, documenti, note), con superfici coerenti.

## Manutenzione

`templates/shared/base.html` carica `static/css/workspace.css` per tutti i ruoli.
`templates/base.html` eredita quella stessa base. Anche i template applicativi
meno recenti ricevono il tema condiviso; i template di dettaglio che usano colori
fissi hanno override mirati per configurazione progetto, avanzamento, produzione,
fiches, grafici, finestre di dialogo e planner. Nessun riordino dei form via JS.

Usare `.workspace-context` con un titolo e `.workspace-context-heading` per
raggruppare operazioni correlate. Le card interne hanno fondo pieno, senza una
seconda linea laterale. I moduli riutilizzano `.form-section`. Non usare colori
fissi per il testo: preferire `--ws-ink`, `--ws-muted` e i token di stato.

Le schede tecniche destinate alla stampa, i PDF e le etichette QR conservano il
foglio chiaro e le convenzioni tecniche. La cornice dell'app segue il nuovo tema.
Swagger `/docs` rimane la documentazione tecnica generata dal framework.

## Verifiche

- `test_workspace_browser.py`: accesso reale dei sei ruoli, link consentiti,
  persistenza del tema, IT/FR, navigazione mobile, card visibili, linee laterali.
- `test_workspace_coverage.py`: 64 schermate operative aperte con database di
  prova, tema giorno/notte, controlli utilizzabili a 390 px e assenza di errori JS.
  Include il contratto di aggiornamento dei colori dei grafici con dati reali
  di prova; il renderer CDN è sostituito soltanto in quel controllo offline.
- Suite esistente: flussi di rapportini, bozze, verifica, pianificazione,
  documenti, autorizzazioni, magazzino, ordini, trasporti e schede tecniche.

Il collaudo esteso ha rilevato e corretto il link CSV della pagina Consumi
cantiere, che passava parametri query come parametri di percorso e causava un
errore di apertura. La reportistica ora mantiene la tabella disponibile anche
quando la libreria esterna dei grafici non viene caricata.

Nessuna migrazione del database o nuova variabile ambiente è richiesta. CSS,
grafici, tema e service worker usano una nuova versione di cache per il rilascio.
