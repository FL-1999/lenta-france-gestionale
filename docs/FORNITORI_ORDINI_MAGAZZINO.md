# Fornitori, ordini e magazzino

## Il principio
Una sola scheda per ogni materiale realmente equivalente, indipendentemente da chi lo vende. Il gestionale genera un codice interno numerico di almeno sei cifre per i nuovi articoli senza codice; i codici esistenti restano invariati. I numeri prenotati non vengono riciclati dopo la cancellazione di un articolo. Eventuali codici storici duplicati non vengono unificati automaticamente.

Esempio illustrativo: il bullone interno **000001** può corrispondere al codice **678** di Mario e **967** di Gianluigi. Entrambe le forniture incrementano la stessa giacenza. La corrispondenza deve essere verificata dall’azienda: dimensione, materiale, classe e unità devono coincidere.

## Come usarlo
1. **Ordini → Fornitori → Nuovo fornitore**: inserisci nome, email e dati disponibili. Salva, poi aggiungi uno o più referenti con funzione, telefono ed email. Puoi disattivare un referente mantenendo gli ordini precedenti.
2. **Magazzino → Nuovo articolo**: inserisci nome, categoria e unità. Il codice interno viene assegnato al salvataggio. Dalla scheda collega ogni fornitore con il codice che usa per quel prodotto. Apri le schede facendo clic sul nome dell’articolo nell’elenco; puoi cercare anche il codice fornitore.
3. Dalla scheda fornitore scegli **Nuovo ordine**. Il fornitore è già selezionato; scegli il referente. Un codice fornitore conosciuto seleziona l’articolo interno. Per un prodotto già in catalogo scegli sempre la scheda esistente. L’opzione **Crea nuovo articolo (pz)** crea invece una nuova scheda a giacenza zero: per altre unità crea prima l’articolo dal magazzino.
4. All’arrivo dei materiali apri l’ordine, scegli **Nuova bolla**, inserisci numero, data e solo le quantità effettivamente ricevute. Puoi salvare una bozza, modificarla oppure **Confermare la ricezione**. Solo la conferma aumenta la giacenza.
5. Se ricevi 4 pezzi su 10, l’ordine resta **PARZIALE** e mostra un residuo di 6. Una seconda bolla da 6 lo porta a **CHIUSO**. Non ricopiare il totale di 10 nella seconda bolla.
6. Nell’ordine trovi le singole bolle con quantità e stato. Nell’elenco scegli **Tutti e storico**, **Da ricevere**, **Consegne parziali** o **Consegnati**. La scheda articolo mostra gli ultimi 50 movimenti; quella fornitore gli ultimi 50 ordini.

## Regole applicate
- Quantità negative, non finite e superiori al residuo vengono rifiutate; nessun ingresso parziale in caso di errore nella conferma.
- Una conferma ripetuta della stessa bolla non crea un secondo carico. Un numero bolla è riconosciuto all’interno del suo ordine; non è un numero globale tra ordini diversi.
- Due bozze possono riferirsi allo stesso residuo, ma alla conferma si ricalcola sempre quanto manca: non si possono ricevere due volte gli stessi quantitativi ordinati.
- Le bolle confermate non sono modificabili. Ordini e fornitori con movimenti registrati sono protetti dalla cancellazione; il fornitore può essere disattivato.
- Gli ordini storici senza collegamento al magazzino mostrano un selettore per associare la riga prima della ricezione. Non si modificano collegamenti di righe già ricevute.
- Un codice dello stesso fornitore non può essere collegato a due materiali diversi. I codici storici ambigui per maiuscole/minuscole richiedono una verifica esplicita.
- Le richieste di prelievo continuano a seguire la conferma del magazziniere già prevista. Questo aggiornamento riguarda gli acquisti e gli ingressi.

## Limiti e passaggi successivi
- **Confezioni:** nessuna conversione automatica scatola/pezzi o bobina/metri. Ordina e ricevi nell’unità dell’articolo. Conversioni per fornitore, listini e minimi d’ordine sono una fase successiva da definire sui vostri acquisti reali.
- **Classificazione:** categorie e macro già presenti sono conservate; nessuna classificazione aziendale inventata e nessuna fusione automatica di materiali somiglianti.
- **Scorte per luogo:** la giacenza di questa scheda è quella centrale già prevista dal gestionale. Per gli ordini cantiere resta il successivo scarico sul cantiere; una contabilità separata per ogni deposito richiede un progetto dedicato.
- La bolla qui è la registrazione di numero, data e quantità; non è stato aggiunto un nuovo archivio di scansioni o PDF delle bolle. Il flusso fatture esistente resta disponibile.
- Resi, annullamento di ricezioni confermate e rettifiche documentali richiedono un flusso specifico: non cancellare lo storico per correggere una consegna.

## Verifica e rilascio
Prove automatiche su codici, referenti, autorizzazioni, collegamenti, ricezioni parziali, duplicati e sovraconsegne. Prova reale nel browser con accesso, creazione fornitore e referenti, articolo, ordine, due bolle e controllo giacenza; controlli di larghezza su telefono. Database di prova isolati, nessun ordine o messaggio inviato a fornitori reali.
La migrazione aggiunge le tabelle referenti/numerazione e il collegamento nullable del catalogo fornitore; conserva i dati esistenti. La verifica autenticata sul database di produzione non è inclusa nelle prove locali.
