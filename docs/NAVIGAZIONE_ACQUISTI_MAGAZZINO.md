# Navigazione B — Acquisti e magazzino

Le cinque sezioni principali si trovano sempre nel menu laterale, nello stesso ordine:
Articoli, Ordini, Fornitori, Movimenti, Richieste. La voce attiva resta evidenziata
anche quando si apre una scheda o un modulo. Su telefono il gruppo si apre con Menu.
Le voci disponibili rispettano i permessi del profilo: il magazziniere non riceve
accesso agli ordini o ai fornitori riservati al manager.

Le vecchie barre centrali che cambiavano da pagina a pagina sono state rimosse.
I filtri degli ordini (in corso, parziali, consegnati) restano dentro Ordini.
La navigazione macro categoria → categoria → articoli resta dentro Articoli.
Categorie, macro categorie, articoli archiviati e sotto soglia si trovano sotto
Organizzazione nel menu laterale. Le schede fornitore mantengono i collegamenti
alle proprie sezioni interne.

## Tornare senza perdere il filo

Un esempio: elenco ordini filtrato → ordine → fornitore → articolo.
Il collegamento «Torna a…» ripercorre quelle pagine al contrario, conservando i
filtri dell'elenco e ripristinando la posizione di scorrimento. Il percorso viene
conservato anche aggiornando la pagina e usando Indietro/Avanti del browser.
Passare a un'altra sezione dal menu laterale riapre l'ultimo elenco consultato
in quella sezione durante la navigazione nell'area acquisti, con i suoi filtri.
Il percorso in alto permette invece di aprire la sezione dall'inizio.

Dopo aver modificato un articolo si torna alla sua scheda. Il salvataggio non
rimanda più all'elenco generale, e «Torna a…» conserva l'elenco di provenienza.

La memoria di navigazione è limitata alla scheda del browser e separata per
utente e ruolo. Non memorizza campi dei moduli né modifica ordini o giacenze.
Aprendo direttamente una pagina in una nuova scheda, oppure se il browser blocca
questa memoria, il ritorno conduce alla sezione o alla scheda padre appropriata.
Senza JavaScript resta disponibile la navigazione normale, senza memoria dei filtri.

## Verifiche

- Pagine e permessi manager, magazziniere e caposquadra.
- Ordine → fornitore → articolo → ritorno all'elenco filtrato.
- Aggiornamento, Indietro/Avanti e salvataggio di un articolo.
- Memoria dei filtri distinta tra Articoli e Ordini.
- Tema giorno/notte, menu mobile e assenza di scorrimento orizzontale.
- Collegamenti di ritorno utilizzabili anche con memoria del browser bloccata.

Non sono necessarie migrazioni del database.
