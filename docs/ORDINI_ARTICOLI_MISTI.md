# Ordini con articoli di categorie diverse

La destinazione (magazzino o cantiere) riguarda l'ordine. La classificazione riguarda ciascun articolo.

1. Seleziona il fornitore e compila data e richiedente.
2. Scegli Magazzino oppure Cantiere. Nel secondo caso seleziona uno dei cantieri attivi disponibili; la destinazione viene salvata nell'ordine.
3. Per ogni riga scegli un articolo esistente, oppure **Crea nuovo articolo**.
4. Per un nuovo articolo scegli l'unità di misura e una delle tre possibilità: categoria esistente; nuova categoria in una macro esistente; nuova macro e nuova categoria.
5. Inserisci codice fornitore, descrizione e quantità. **Aggiungi articolo** aggiunge una riga indipendente.

Per ripetere una nuova macro/categoria in più righe, inserisci gli stessi nomi: al salvataggio viene riutilizzata la stessa classificazione. Un nome di categoria già appartenente a un'altra macro genera un messaggio esplicito, senza spostare la categoria esistente.

I codici fornitore già collegati richiamano l'articolo interno esistente. Gli articoli esistenti mantengono la propria classificazione e unità. La creazione dell'ordine non aumenta la giacenza: l'articolo nasce a quantità zero. I flussi di bolle e conferma ricezione restano quelli esistenti.

Un errore su una riga annulla l'intero salvataggio: non rimangono macro, categorie, articoli o ordini parzialmente creati. Il modulo ripropone i dati inseriti. Non è necessaria una migrazione del database. I moduli della versione precedente già aperti continuano ad accettare il salvataggio con categoria comune.
