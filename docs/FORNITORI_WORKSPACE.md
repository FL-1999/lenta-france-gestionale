# Fornitori: elenco e scheda operativa

La sezione usa il tema condiviso del gestionale: blu notte, giorno grigio caldo, azioni principali rosse e sezioni con bordo laterale.

## Utilizzo

1. Da **Magazzino → Fornitori** cerca per nome, email, città o nome/email di un referente. I filtri Tutti, Attivi e Disattivi mantengono la ricerca; i conteggi si riferiscono ai risultati della ricerca. Azzera rimuove ricerca e filtro.
2. **Apri scheda** mostra dati aziendali, referenti, articoli collegati e storico ordini. **Nuovo ordine** precompila il fornitore; è disponibile solo per fornitori attivi.
3. **Modifica dati aziendali** apre il modulo di modifica. Il nome è obbligatorio, gli altri dati sono facoltativi.
4. In **Referenti**, apri un nome per modificarlo, oppure **Aggiungi referente**. Deselezionare “Disponibile negli ordini” esclude quel referente dai nuovi ordini senza cancellarlo.
5. Gli articoli mostrano codice fornitore e collegamento alla scheda interna di magazzino. L'associazione di più fornitori allo stesso articolo resta disponibile nella scheda articolo.
6. Lo **Storico ordini** mostra 20 ordini per pagina, compresi quelli chiusi. La navigazione permette di raggiungere anche gli ordini oltre i 50 più recenti.
7. **Gestisci fornitore** contiene disattivazione ed eliminazione, separate dalle azioni quotidiane. Le protezioni esistenti contro l'eliminazione di fornitori con consegne confermate o movimenti di magazzino rimangono in vigore.

L'elenco fornitori è alfabetico e mostra 30 risultati per pagina. Nessuna modifica allo schema del database o alle giacenze.

## Verifica

Test automatici per ricerca per referente senza duplicati, filtri, caratteri letterali, paginazione e isolamento dello storico per fornitore. Prove browser per modifica anagrafica e referente, nuovo ordine precompilato, disattivazione, temi e schermi piccoli. Il flusso browser esistente copre inoltre creazione fornitore, due referenti, collegamento articolo e ricezioni parziale/finale.
