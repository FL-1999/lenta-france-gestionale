# Magazzino A1

La pagina **Magazzino** mostra le macro categorie effettivamente presenti nel catalogo. Apri una macro per vedere le categorie, poi una categoria per vedere i suoi articoli. Il percorso in alto permette di tornare ai livelli precedenti. **Tutti gli articoli** apre l'elenco completo; la ricerca permette di trovare direttamente un materiale. Non vengono create categorie dimostrative né riclassificati i dati esistenti. Le voci senza classificazione restano accessibili.

- Seleziona una famiglia oppure cerca per nome, codice interno o codice fornitore.
- **Apri scheda** mostra giacenza, fornitori equivalenti, posizione e ultimi movimenti.
- **Aggiungi posizione** permette di compilare zona, scaffale e ripiano/contenitore: ogni campo è facoltativo. **Rimuovi posizione** cancella solo queste informazioni.
- Manager e operatori con il permesso di gestione inventario possono aggiornare la posizione. La modifica è registrata nello storico di audit e non modifica quantità, codici o collegamenti ai fornitori.
- Uno stesso articolo può avere più di due fornitori: non è previsto un limite di due. I codici devono identificare materiali equivalenti nella stessa unità di misura.
- Carico/scarico rapido si trovano nella scheda, sotto **Carichi e prelievi**, con gli stessi permessi e controlli precedenti. Duplicazione, preferiti, rettifica e archiviazione sono sotto **Gestione articolo**.

Il logo tipografico è condiviso da menu e accesso al gestionale, per tutti i ruoli. Il file del logo originale e i riferimenti nelle fiches, nei documenti e nelle etichette restano invariati.

## Correggere un’unità di misura errata

Da **Scheda articolo → Modifica articolo**, cambia **Unità di misura**, spunta la conferma della correzione e salva. Si usano gli stessi permessi della modifica articolo, sia su PC sia su telefono.

È una correzione dell’etichetta: ad esempio 10 pz inseriti per errore diventano 10 m. La sola modifica dell’unità non converte giacenza, movimenti, richieste, quantità ordinate/ricevute, soglia o costo, e non genera un movimento di rettifica. Le viste collegate leggono l’unità corretta dall’articolo; i documenti già generati e i dati originali del catalogo fornitore non sono riscritti. Non usare questa correzione per convertire una contabilità già corretta da sacchi a kg: per carichi in confezioni usa le equivalenze.

Confezioni e quantità inserite nel modulo vengono validate rispetto alla nuova unità. Il salvataggio registra vecchia e nuova unità nell’audit e rifiuta una scheda aperta prima di un’altra correzione. Non servono nuove colonne o migrazioni.

## Aggiornamento

All'avvio vengono aggiunte tre colonne nullable alla tabella articoli tramite il meccanismo di aggiornamento già utilizzato dal gestionale. Le schede esistenti iniziano senza posizione. Non occorre compilare né importare ubicazioni prima di usare la nuova schermata.
