# Elenco ordini e storico fornitori

La pagina Ordini e l'archivio degli ordini chiusi condividono lo stile del magazzino: superfici blu nel tema notte, grigio caldo nel tema giorno, bordo laterale, icone lineari e azione principale rossa.

- Schede In corso (comprende i parziali), Parziali, Chiusi e Tutti. I conteggi rispettano ricerca, fornitore, tipo e date selezionate, prima del filtro sullo stato.
- Ricerca per numero ordine, descrizione, nome o email del fornitore. La selezione Fornitore identifica esattamente la sua anagrafica, anche se disattivata, per consultare lo storico.
- Filtri per ordini di magazzino/cantiere e intervallo date. I filtri restano attivi cambiando stato o pagina.
- Elenco di 20 ordini per pagina, ordinato per data decrescente e identificativo a parità di data. Le date mancanti sono in fondo.
- Ogni riga mostra numero, fornitore, descrizione, data, richiedente, destinazione, avanzamento ricezione e bolle confermate. I comandi e le informazioni si dispongono in verticale sul telefono.
- Lo storico nella scheda fornitore usa le stesse righe e un pulsante Filtra gli ordini apre l'elenco completo per quel fornitore.

Gli stati storici `CHIUSO` e `completato`, senza distinzione tra maiuscole e minuscole, confluiscono entrambi nell'archivio. Le bolle in bozza sono escluse dall'avanzamento e dal conteggio delle bolle confermate. Il calcolo percentuale preesistente sulle quantità ordinate/ricevute resta invariato; non è una misura economica.

Nessuna migrazione e nessuna modifica alle procedure di creazione, ricezione, invio email o movimento delle giacenze. Le nuove query di elenco sono paginate e i riepiloghi delle consegne sono caricati in gruppo per gli ordini della pagina.

Verifiche: filtri combinati, stato storico completato, paginazione stabile, ricerca letterale, permessi, bolle confermate/bozze, navigazione dallo storico fornitore. Browser su ordini, chiusi e scheda fornitore nei due temi a 1440 e 390 pixel.
