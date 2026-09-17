# Magazzino A1

La pagina **Magazzino** mostra le famiglie effettivamente presenti nel catalogo e un elenco compatto degli articoli. Non vengono create categorie dimostrative né riclassificati i dati esistenti. I precedenti raggruppamenti restano disponibili in **Gestisci**.

- Seleziona una famiglia oppure cerca per nome, codice interno o codice fornitore.
- **Apri scheda** mostra giacenza, fornitori equivalenti, posizione e ultimi movimenti.
- **Aggiungi posizione** permette di compilare zona, scaffale e ripiano/contenitore: ogni campo è facoltativo. **Rimuovi posizione** cancella solo queste informazioni.
- Manager e operatori con il permesso di gestione inventario possono aggiornare la posizione. La modifica è registrata nello storico di audit e non modifica quantità, codici o collegamenti ai fornitori.
- Uno stesso articolo può avere più di due fornitori: non è previsto un limite di due. I codici devono identificare materiali equivalenti nella stessa unità di misura.
- Carico/scarico rapido si trovano nella scheda, sotto **Carichi e prelievi**, con gli stessi permessi e controlli precedenti. Duplicazione, preferiti, rettifica e archiviazione sono sotto **Gestione articolo**.

Il logo tipografico è condiviso da menu e accesso al gestionale, per tutti i ruoli. Il file del logo originale e i riferimenti nelle fiches, nei documenti e nelle etichette restano invariati.

## Aggiornamento

All'avvio vengono aggiunte tre colonne nullable alla tabella articoli tramite il meccanismo di aggiornamento già utilizzato dal gestionale. Le schede esistenti iniziano senza posizione. Non occorre compilare né importare ubicazioni prima di usare la nuova schermata.
