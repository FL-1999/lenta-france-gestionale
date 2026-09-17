# Articoli, fornitori e ordini

## Creazione senza ordine

In **Magazzino → Nuovo articolo**:

1. Inserire nome, macro/categoria e unità. Il codice interno viene assegnato automaticamente.
2. Inserire l'eventuale giacenza iniziale, soglia minima e costo.
3. La sezione **Fornitori e codici** è facoltativa. Usare **Aggiungi fornitore** per ogni associazione: selezionare un fornitore esistente e inserire il codice che utilizza per quell'articolo. Sono supportati anche tre, quattro o più fornitori.
4. Salvare. Articolo, associazioni e carico iniziale vengono salvati insieme. Le righe vuote non obbligano ad associare un fornitore; le righe compilate solo a metà devono essere completate o rimosse.

Un codice dello stesso fornitore già assegnato a un altro articolo viene rifiutato: il modulo conserva i dati inseriti e non crea un articolo o una giacenza parziale. I codici storici senza collegamento possono essere associati senza duplicarli.

## Associazione successiva

Aprire la scheda articolo e la sezione **Fornitori e codici equivalenti**, selezionare il fornitore, inserire il suo codice e premere **Collega fornitore**. Eventuali conflitti sono mostrati nella stessa pagina.

## Ordini

- **Ordina articolo** sulla scheda di magazzino apre un nuovo ordine con fornitore, articolo e relativo codice già scelti. Rimane da indicare la quantità e completare l'ordine.
- Nel nuovo ordine la ricerca **Articolo interno — codice o nome** filtra la selezione degli articoli esistenti.
- Il **codice fornitore è facoltativo**. Se l'associazione è già nota e univoca viene compilato automaticamente. Con più codici dello stesso fornitore si può scegliere quello desiderato.
- Inserendo un nuovo codice fornitore insieme all'articolo interno, l'ordine salva l'associazione. Inserendo un codice già collegato, viene selezionato il relativo articolo.
- Cambiando articolo o fornitore i suggerimenti vengono aggiornati, evitando di mantenere automaticamente il codice del precedente articolo.

La ricerca del magazzino riconosce nome, codice interno e codici fornitori. L'associazione di fornitori non cambia la giacenza: un ordine aumenta il magazzino solo attraverso la ricezione confermata già prevista dal sistema.

## Interfaccia e verifiche

Regole comuni di allineamento per campi, filtri e pulsanti delle pagine magazzino; intestazioni e comandi delle categorie con icone lineari, menu coerenti nei temi giorno/notte. Nessuna migrazione del database.

Test su dati isolati: creazione con quattro fornitori, ricerca, creazione facoltativa, associazione successiva, conflitti e permessi, ordini precompilati e nuovi codici. Percorso browser su 21 viste magazzino a 1440 e 390 pixel; schermate giorno/notte.
