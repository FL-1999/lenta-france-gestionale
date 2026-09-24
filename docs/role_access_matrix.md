# Accessi effettivi del gestionale

Verifica del codice: 24 settembre 2026. Le autorizzazioni ordinarie seguono il ruolo attivo, non la somma dei ruoli assegnati.

| Funzione | Admin | Manager | Magazzino |
| --- | --- | --- | --- |
| Cantieri, piante, coupe, fiches, rapportini, personale | Gestisce | Gestisce | Non accede |
| Articoli, scorte, richieste e movimenti | Gestisce | Gestisce | Consulta articoli; gestisce carichi, prelievi, richieste e posizioni |
| Creazione e modifica catalogo, categorie, fornitori e ordini d'acquisto | Gestisce | Gestisce | Non gestisce |
| Costi unitari degli articoli | Modifica | Modifica | Consulta |
| Preparazione carichi per viaggi esistenti | Gestisce | Gestisce | Gestisce |
| Creazione viaggi, assegnazione autisti | Gestisce | Gestisce | Non gestisce |
| Depositi | Gestisce | Gestisce | Consulta |
| Utenti, ruoli, disattivazione/eliminazione profili | Gestisce | Non accede | Non accede |
| Impostazioni, backup e SharePoint | Gestisce | Non accede | Non accede |
| Eliminazioni protette da sites.delete o records.delete | Consentite | Non consentite | Non consentite |
| Costi economici dei cantieri | Gestisce | Gestisce | Non accede |
| Ricavi e margini dei cantieri | Accede | Non accede se ha solo il ruolo manager | Non accede |

Il cestino privato e il recupero copie SharePoint richiedono anche la corrispondenza con `CLOUD_ARCHIVE_OWNER_EMAIL`: essere admin da solo non basta.

Eccezione già presente: `can_view_site_margin` verifica anche il ruolo admin assegnato. Un account admin che passa alla vista manager può continuare a vedere margini/ricavi; per collaudare un manager puro usare un account senza ruolo admin assegnato. Questa revisione non modifica tale regola.

Il permesso nominale `equipment.read` del magazzino non apre il catalogo amministrativo `/manager/attrezzature`, che oggi richiede `manager.access`. Il magazziniere accede alle attrezzature e ai carichi tramite i trasporti. Non mostrare scorciatoie verso pagine amministrative non autorizzate.

## Prezzi e valore delle scorte

Da **Dashboard magazzino → Prezzi e valorizzazione**, oppure **Acquisti e magazzino → Prezzi**, cercare un articolo e salvare il costo unitario. La stessa pagina è raggiungibile dalla scheda articolo. Admin e manager modificano; magazzino consulta.

Il totale è la somma di `quantita_disponibile × costo_unitario` degli articoli attivi con costo. Un costo assente non contribuisce al totale ed è segnalato come mancante; il valore zero è invece un costo registrato. Si tratta del costo di riferimento inserito manualmente, non di FIFO, costo medio ponderato o prezzo di vendita. Il costo non viene aggiornato automaticamente da fatture o ordini.

L'unità è quella dell'articolo: per un articolo in kg, il costo è €/kg anche se le entrate vengono registrate in sacchi o bancali tramite le conversioni disponibili. Esempio: 100 kg × 0,20 €/kg = 20 €. Cambiare costo rivalorizza la giacenza attuale senza creare movimenti, modificare quantità o riscrivere prezzi di ordini precedenti.

La pagina segnala dati non validi senza svuotare il valore inserito e rileva modifiche concorrenti. Le variazioni sono registrate nell'audit. I campi costo/soglia nell'editor completo rifiutano valori negativi o non finiti.
