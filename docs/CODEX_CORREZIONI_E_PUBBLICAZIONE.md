# Correzioni del gestionale e pubblicazione su Render

Preparato il 15 settembre 2026. Ambito A: gestionale interno. Il sito pubblico rimane un progetto separato.

## Cosa cambia nell'uso quotidiano

- Gli utenti disattivati non possono continuare ad accedere alle API dei cantieri. I token di rinnovo non possono essere usati come credenziali di accesso alle pagine o alle API.
- L'avvio non crea più un amministratore con credenziali predefinite e non cambia password, ruoli o stato degli utenti esistenti.
- Fiches e rapportini sono riservati ai ruoli admin, manager e caposquadra; restano i controlli sui cantieri assegnati al caposquadra.
- I manager gestiscono i costi, ma non ricevono i movimenti dei ricavi né i riepiloghi di margine riservati. Salvare i costi del budget conserva il ricavo previsto. Modificare, riclassificare o cancellare un ricavo e cancellare l'intero budget richiede il permesso già previsto per i dati riservati.
- La preparazione del carico aggiunge le selezioni e conserva il materiale già salvato o scansionato. Una selezione duplicata, inesistente, occupata o del tipo sbagliato viene respinta prima di modificare il carico. Le selezioni vuote non cancellano nulla. Il carico manuale è modificabile prima della partenza.
- Lo scanner distingue **Carica** e **Scarica**. Dopo ogni lettura si preme **Scansiona il prossimo QR**. Ripetere la stessa operazione non la inverte. Il nome dell'attrezzatura viene mostrato come testo, senza interpretarlo come HTML.
- Chiudere due volte un viaggio non duplica i movimenti. Le attrezzature dichiarate ancora sul camion restano in trasporto; quelle già scaricate non vengono spostate di nuovo dalla chiusura del vecchio viaggio.
- Su telefono sono raggiungibili il menu account e il logout. Il collegamento Trasporti dell'autista porta alla sua pagina. I titoli delle schede del browser rispettano quelli delle singole pagine.

## Cosa è stato controllato

Il codice parte da `main`, commit `e9ff3e41a5666bc2c016c00f130f6d695385552e`, coincidente al momento del prelievo con il ramo dell'handover. I 142 test iniziali passavano. Sono state aggiunte prove di regressione per accessi, ricavi, budget, carichi ripetuti, QR e chiusura viaggio. Le prove nel browser usano dati fittizi e una fotocamera simulata, su larghezze di 320 e 390 pixel; verificano anche il logout e le richieste reali allo scanner dell'applicazione locale.

I test usano sempre un database SQLite temporaneo, anche se il computer contiene variabili di ambiente per un database reale. La procedura GitHub Actions esegue i test anche in Linux con Chromium. L'esito definitivo su GitHub è quello mostrato nella richiesta di modifica.

Non sono stati usati né modificati il database di produzione, gli account reali o le impostazioni Render. Nessuna modifica allo schema del database è introdotta da questo pacchetto. Il blocco concorrente delle righe è previsto per PostgreSQL, ma non è stato collaudato su una copia del database di produzione. I test non certificano le fotocamere dei singoli telefoni, il GPS esterno o tutti gli export PDF.

## Prima di aggiornare Render

1. **Accertare dove sono salvati i dati e avere un backup ripristinabile.** In Render, nella pagina del servizio, controllare la presenza di `DATABASE_URL` in Environment senza copiarne il valore in chat. Se non c'è, il codice usa SQLite: prima di un nuovo deploy va verificato che il file risieda su un disco persistente. Un file sul disco temporaneo del servizio può andare perso con un deploy. Il backup del codice su GitHub non è un backup dei dati. Anche gli allegati caricati dall'applicazione devono essere conservati.
2. **Conservare le impostazioni esistenti del database e delle sessioni.** Non sostituire `DATABASE_URL` o `SECRET_KEY` con valori di prova. Se l'account amministratore esiste già, questo aggiornamento non richiede di ricrearlo. Solo per un database nuovo, la creazione automatica richiede `ADMIN_EMAIL` e `ADMIN_PASSWORD` configurate esplicitamente. `ADMIN_FORCE_RESET` non reimposta più gli utenti all'avvio: un eventuale recupero va svolto come operazione esplicita.
3. Se viene ancora usata la password iniziale predefinita della vecchia versione, cambiarla dalla gestione utenti prima della pubblicazione. Rimuovere il fallback dal codice non cambia le password già salvate.
4. Aprire la richiesta di modifica su GitHub e aspettare che i controlli siano verdi. Se uno fallisce, consultare il risultato prima di procedere.

## Come attivare le modifiche

Dalle schermate fornite, Render segue **main** con **Auto-Deploy: On Commit**.

1. Nella richiesta di modifica GitHub premere **Merge pull request**, poi **Confirm merge**, quando si intende aggiornare il gestionale.
2. Render avvia automaticamente la pubblicazione. Nella pagina del servizio controllare **Events** e attendere il completamento del nuovo deploy.
3. Aprire il gestionale e ricaricare la pagina. Su un dispositivo dove era già aperto lo scanner, chiudere la vecchia scheda e riaprirlo.
4. Verificare login, apertura di un cantiere, accesso ai costi con un manager e menu account dal telefono. Per provare scritture e QR usare un viaggio e attrezzature dedicati al collaudo: ogni operazione nel gestionale reale registra dati reali.

Non serve cambiare il ramo Render, caricare file manualmente, modificare il comando di avvio o comunicare il deploy hook.

Con la modalità On Commit il deploy parte appena cambia main: i controlli sul ramo non costituiscono automaticamente un blocco al merge. Documentazione: [Deploy su Render](https://render.com/docs/deploys).

## Se qualcosa non funziona

Annotare il messaggio di errore e l'ora. Se serve tornare alla versione precedente, dalla cronologia deploy di Render selezionare l'ultima versione funzionante e l'azione di rollback. Il rollback ripristina il codice e non annulla i dati scritti nel frattempo. Il rollback dalla dashboard disattiva gli aggiornamenti automatici: riattivarli solo dopo aver corretto la causa. Documentazione: [Rollback Render](https://render.com/docs/rollbacks).

## Lavoro successivo, separato da questo pacchetto

Restano da affrontare: revoca delle sessioni di rinnovo lato server, migrazioni e verifica del ripristino database, versioni riproducibili delle dipendenze, verifica completa della tracciabilità delle attrezzature, integrazione GPS reale e funzionamento offline/PWA. Questo pacchetto non pretende di risolvere l'intero audit o di ridisegnare il gestionale.

Per B: il sito pubblico IT/FR va costruito separatamente. Clienti prioritari, servizi, referenze, certificazioni, foto, dominio e conversione desiderata restano **DA CONFERMARE**.
