# Pianta cantiere: importazione ibrida

La pagina `GET /manager/cantieri/{site_id}/pianta` è collegata alle schede manager e caposquadra. Il manager importa un PDF, sceglie la pagina e corregge i pannelli in bozza; i capisquadra assegnati consultano solo disegni convalidati. Il PDF originale resta immutato e disponibile affiancato o completo in una scheda separata.

## Riconoscimento

Il riconoscitore estrae testi orientati e segmenti dai PDF vettoriali. Propone pannelli con sigle `P` + numero + suffisso, cerca contorni vicini e quote decimali parallele. Non usa coordinate predefinite di Papon, servizi esterni, né i colori del PDF per dedurre avanzamenti o controlli. Le scansioni e le convenzioni non riconosciute possono essere tracciate manualmente. Non è presente OCR.

Ogni proposta richiede verifica esplicita. Contorni mancanti, sigle ripetute, quote mancanti e incoerenze rispetto alla scala prevalente vengono segnalati. Una sagoma proposta non è una misura certificata: il confronto con l'originale rimane necessario. Sul PDF Papon usato localmente sono state estratte 29 occorrenze di sigle e 29 larghezze; P8b richiede verifica degli estremi. Il file cliente non è incluso nel repository.

## Modifica e convalida

- Modifica sigla e larghezza, sposta una sagoma, trascina gli angoli oppure imposta centro, lunghezza grafica, spessore grafico e angolo.
- La larghezza in metri e le coordinate grafiche sono campi diversi. La scala comune (punti del PDF per metro) viene stimata dai contorni quotati e si può ricalibrare su un pannello noto. Il comando di adattamento usa questa scala con centro, inizio o fine fissi; non cambia le dimensioni delle fiches.
- Le lunghezze dei due lati longitudinali devono rispettare la scala entro il 2% prima della convalida. Il riconoscitore cerca estremi compatibili con la quota oltre le intersezioni interne (caso P8b), poi proporziona le larghezze alla stessa scala. Quote non decimali o ambigue richiedono inserimento manuale in metri.
- Uno scostamento dalla sagoma originariamente riconosciuta o dai bordi del foglio richiede conferma separata dello sbordo. Non viene dedotto un perimetro strutturale dal PDF: il controllo segnala possibili sbordi, che il responsabile confronta con l’originale. Le coordinate non vengono tagliate ai bordi; lo spazio massimo ammesso arriva a un foglio aggiuntivo per lato.
- Aggiungi un rettangolo trascinando sulla pianta; rimuovi una zona con conferma. Nessuna di queste azioni cancella fiches.
- La convalida richiede almeno un pannello, sagome convesse valide, larghezze positive e verifica esplicita di ogni pannello. Alla convalida i pannelli non collegati ricevono identità interne stabili e sigle nella griglia progetto. Non si creano fiche di produzione fittizie.
- Dopo la convalida, il disegno operativo è separato dalla bozza. Ulteriori modifiche richiedono `Modifica bozza` e una nuova convalida. Un nuovo PDF resta una bozza e non sostituisce il disegno attivo automaticamente. Il disegno operativo è quello con convalida più recente.
- Il contatore di revisione evita salvataggi concorrenti e sovrascritture da schede obsolete. Il log audit registra importazioni, salvataggi e convalide. Per uno stesso PDF viene conservato l'ultimo snapshot convalidato, non una cronologia di tutti gli snapshot intermedi. I precedenti PDF importati restano consultabili.

## Collegamenti e avanzamento

L'identità della zona è distinta dalla sigla visualizzata, quindi le sigle duplicate sono valide. Il collegamento a un elemento paratia già configurato è proposto automaticamente solo se il nome personalizzato corrisponde in modo univoco. Gli altri collegamenti si scelgono nel menu: non vengono dedotti dall'ordine di estrazione del PDF. Un elemento non può essere associato a due zone nello stesso disegno.

Il dettaglio legge i dati dalle fiches/coupe/controlli esistenti. Distingue `Da eseguire`, `Fiche presente`, `Getto registrato` (data getto e metri cubi valorizzati). La griglia di avanzamento preesistente non viene alterata. L'importazione prepara solo una bozza. La convalida crea gli elementi mancanti e aggiorna il totale, preservando gli elementi già usati. Le misure della pianta non sovrascrivono fiche salvate; la larghezza viene proposta nelle nuove fiche. Le coupe si configurano dopo la convalida. I contrassegni S/I provengono dai controlli configurati, non dal colore del PDF.

## Persistenza, limiti e verifiche

Nuova tabella `site_plans`, creata dal bootstrap metadata esistente, con PDF/anteprima binari differiti e layout JSON. Nessuna modifica ai record di produzione preesistenti; relazione con cancellazione del cantiere tramite cascade ORM. Dipendenze: pdfplumber e pypdfium2. PDF fino a 15 MB, massimo 500 pannelli per pianta; controllo della complessità, geometrie e coordinate finite; rendering PDFium serializzato tra thread.

Test: `tests/test_site_plans.py` copre PDF vettoriali reali sintetici, testi ruotati, permessi, conservazione originale, collegamenti, convalida, geometrie invalide, bozza separata e conflitti di revisione. `tests/test_site_plans_browser.py` esercita il flusso con login reale e database isolato, incluso trascinamento, modifica, salvataggio, convalida e viste responsive giorno/notte. Il file cliente può essere fornito solo localmente tramite `SITE_PLAN_SAMPLE_PDF`; normalmente il test utilizza un PDF sintetico.

## Coupe e produzione

### Coupe paratie e coupe pali

Le due sezioni hanno coupe distinte, identificate da `site_coupes.tipologia_scavo` (colonna nullable aggiunta dal bootstrap). Le coupe paratie definiscono spessore, quote, profondità prevista, stratigrafia e armatura; non definiscono una larghezza comune. La larghezza delle nuove fiches viene dal singolo pannello convalidato (oppure dallo sviluppo netto dell’angolo A/B). Senza pianta, la larghezza va inserita nella singola fiche. Il vecchio campo `larghezza` rimane conservato per compatibilità storica ma non è più un valore proposto o modificabile nella coupe.

Nelle nuove fiches il server rifiuta una larghezza diversa dal pannello convalidato o uno spessore diverso dalla coupe. I campi corrispondenti vengono compilati automaticamente e resi di sola lettura nel modulo di creazione. Quote e profondità effettiva della produzione mantengono i controlli preesistenti. Le fiches storiche e i relativi snapshot non vengono riscritti.

Le coupe pali hanno diametro e associazioni ai pali, senza campo larghezza o spessore paratia. Il server impedisce associazioni miste e cambi di tipo incompatibili con fiches già salvate. Per i record precedenti senza tipo esplicito, il tipo viene dedotto dalle associazioni/fiches (poi dalle dimensioni se non ci sono associazioni). Le vecchie coupe miste rimangono consultabili in `Da separare`: i dati storici non vengono redistribuiti automaticamente.

`test_coupe_dimensions.py` verifica pannelli da 6,40 e 3,50 m nella stessa coupe, volumi, controlli server e tipi separati; `test_coupe_dimensions_browser.py` verifica schede dedicate e passaggio fra pannelli nel modulo fiche.

### Modifica guidata e angoli A/B

Il riquadro geometria è separato dalle informazioni e conferme del pannello. I lati interi si trascinano o si spostano di 1, 5 o 10 cm: con larghezza bloccata le due testate traslano insieme, sbloccandola una testata varia la larghezza in metri alla scala comune. I lati collegati rimangono paralleli. Per muovere liberamente i vertici occorre disattivare entrambi i blocchi. La vista trasparente e l’opacità dei vicini aiutano il confronto con il PDF; le modifiche geometriche si possono annullare.

L’importazione propone coppie A/B solo con numero univoco, vicinanza e direzioni trasversali. `Riconosci angoli A/B` applica lo stesso criterio alle bozze già esistenti. Le misure restano quelle dei singoli bracci e richiedono controllo: una quota riconosciuta male non diventa corretta con il raggruppamento. `Raccorda angolo` accosta bordi paralleli con una traslazione rigida, senza deformare le sagome; le direzioni incompatibili richiedono correzione manuale. Il trascinamento del corpo sposta entrambi i bracci, le maniglie modificano solo quello selezionato.

Prima della convalida il server richiede un contatto tra i bordi, assenza di sovrapposizione e conferma delle larghezze nette (intersezione conteggiata una sola volta). I due pannelli conservano identità e sigle proprie. Dopo l’assegnazione alla stessa coupe completa, il salvataggio crea il gruppo `P3 A/B` per una fiche unica; prima di tale assegnazione non si possono creare fiche individuali per quei bracci. Non vengono create automaticamente fiche di produzione. Le quote della coupe aggiornano il gruppo ancora privo di fiche; una fiche esistente conserva i propri dati storici.

`Separa angolo` rimuove il raggruppamento in bozza lasciando ferme entrambe le sagome. Alla convalida può sciogliere un gruppo senza fiche; se il gruppo ha produzione, richiede prima la gestione esplicita dalla pagina cantiere e annulla l’intera operazione. Anche la rimozione di un’associazione coupe necessaria a una fiche viene bloccata. Nessuna fiche viene cancellata dalla pianta.

Verifiche: `test_plan_corners.py` copre importazione proposta, raccordi invalidi, convalida, creazione coupe, fiche unica, conservazione e separazione; `test_plan_corner_editor_browser.py` prova i comandi reali, trascinamenti, scala, persistenza e viste IT/FR, desktop e mobile.

La navigazione Pianta → Coupe → Fiches mantiene il contesto del cantiere. Le coupe non vengono create automaticamente: il responsabile crea ciascun gruppo con nome, quote, dimensioni e descrizione dell’armatura/riferimento tavola. Il campo armatura è descrittivo, non calcola ferri o gabbie. Viene conservato nello snapshot della fiche e riportato nel rapporto. Le coupe hanno pannelli selezionabili sulla pianta o tramite pulsanti, ricerca e selezione multipla. Un pannello assegnato a un'altra coupe è disabilitato; il server rifiuta duplicazioni anche per richieste manuali e annulla l'intero salvataggio. Controlli sonici/inclinometri rimangono indipendenti dalle coupe.

Da un pannello convalidato senza fiche si apre il modulo esistente con cantiere, numero interno, sigla, coupe e larghezza. Il modulo offre anche un selettore della pianta nella normale creazione. La fiche resta unica per cantiere/tipo/identità; nomi duplicati non confondono i collegamenti.

`site_coupes.quota_reference_label` è un'etichetta (default NGF), mai una conversione di datum. La profondità può derivare da partenza scavo meno fondo. La partenza è TN o la quota alternativa della coupe. Le nuove fiche conservano sigla, etichetta e uno snapshot dei parametri coupe per la stampa storica. I campi aggiunti sono nullable e migrati dal bootstrap esistente.

Il rapporto conserva il logo documentale, il disegno 3D e le misure in metri. L'esportazione singola e `/manager/cantieri/{id}/fiches-pdf/tutte` usano lo stesso articolo tecnico; il dossier completo aggiunge una copertina e comprende paratie e pali. `tests/test_plan_coupe_fiche_flow.py` verifica identità, conversione quote, snapshot e rollback; `tests/test_plan_coupe_fiche_browser.py` verifica selezione, creazione reale e PDF esportati via HTTP.
