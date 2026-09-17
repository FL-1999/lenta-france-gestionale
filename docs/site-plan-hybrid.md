# Pianta cantiere: importazione ibrida

La pagina `GET /manager/cantieri/{site_id}/pianta` è collegata alle schede manager e caposquadra. Il manager importa un PDF, sceglie la pagina e corregge i pannelli in bozza; i capisquadra assegnati consultano solo disegni convalidati. Il PDF originale resta immutato e disponibile affiancato o completo in una scheda separata.

## Riconoscimento

Il riconoscitore estrae testi orientati e segmenti dai PDF vettoriali. Propone pannelli con sigle `P` + numero + suffisso, cerca contorni vicini e quote decimali parallele. Non usa coordinate predefinite di Papon, servizi esterni, né i colori del PDF per dedurre avanzamenti o controlli. Le scansioni e le convenzioni non riconosciute possono essere tracciate manualmente. Non è presente OCR.

Ogni proposta richiede verifica esplicita. Contorni mancanti, sigle ripetute, quote mancanti e incoerenze rispetto alla scala prevalente vengono segnalati. Una sagoma proposta non è una misura certificata: il confronto con l'originale rimane necessario. Sul PDF Papon usato localmente sono state estratte 29 occorrenze di sigle e 29 larghezze; P8b richiede verifica degli estremi. Il file cliente non è incluso nel repository.

## Modifica e convalida

- Modifica sigla e larghezza, sposta una sagoma, trascina gli angoli oppure imposta centro, lunghezza grafica, spessore grafico e angolo.
- La larghezza in metri e le coordinate grafiche sono campi diversi. Il comando esplicito di adattamento ridimensiona la sagoma rispetto alla larghezza di riferimento della sessione; non cambia le dimensioni delle fiches.
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

La navigazione Pianta → Coupe → Fiches mantiene il contesto del cantiere. Le coupe hanno pannelli selezionabili sulla pianta o tramite pulsanti, ricerca e selezione multipla. Un pannello assegnato a un'altra coupe è disabilitato; il server rifiuta duplicazioni anche per richieste manuali e annulla l'intero salvataggio. Controlli sonici/inclinometri rimangono indipendenti dalle coupe.

Da un pannello convalidato senza fiche si apre il modulo esistente con cantiere, numero interno, sigla, coupe e larghezza. Il modulo offre anche un selettore della pianta nella normale creazione. La fiche resta unica per cantiere/tipo/identità; nomi duplicati non confondono i collegamenti.

`site_coupes.quota_reference_label` è un'etichetta (default NGF), mai una conversione di datum. La profondità può derivare da partenza scavo meno fondo. La partenza è TN o la quota alternativa della coupe. Le nuove fiche conservano sigla, etichetta e uno snapshot dei parametri coupe per la stampa storica. I campi aggiunti sono nullable e migrati dal bootstrap esistente.

Il rapporto conserva il logo documentale, il disegno 3D e le misure in metri. L'esportazione singola e `/manager/cantieri/{id}/fiches-pdf/tutte` usano lo stesso articolo tecnico; il dossier completo aggiunge una copertina e comprende paratie e pali. `tests/test_plan_coupe_fiche_flow.py` verifica identità, conversione quote, snapshot e rollback; `tests/test_plan_coupe_fiche_browser.py` verifica selezione, creazione reale e PDF esportati via HTTP.
