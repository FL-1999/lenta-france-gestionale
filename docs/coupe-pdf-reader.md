# Lettura assistita delle coupe

Nella configurazione coupe, «Leggi una coupe PDF» legge una pagina di un PDF
vettoriale (massimo 15 MB). Il rettangolo di selezione delimita la sezione, titolo
e quote compresi. Più titoli coupe nella selezione bloccano l'inserimento.
Scansioni senza testo restano da compilare manualmente: non è presente OCR.

I campi riconosciuti sono proposte da verificare. L'inserimento nel modulo non
scrive nel database; solo il normale salvataggio del modulo conserva la coupe.
Serve la conferma del controllo del disegno. Gli errori restituiscono il modulo
con i dati, le righe aggiunte e le informazioni di origine ancora presenti.
Non vengono associati automaticamente pannelli o cambiate fiches esistenti.

## Convenzioni

- TN, Tête PM, Base PM mécanique/hydraulique: quote NGF, numeri con punto o virgola.
- Ht et Htot in metri permettono di proporre le basi dalla testa. Eventuali quote
  Base PM devono essere coerenti; differenze oltre 2 cm richiedono correzione.
- La profondità da TN è TN meno base totale; non è Htot dalla testa della paratia.
- «Axe du buton», «Axe de buton» o «Axe buton» con una singola quota NGF
  identificano il livello. Colore blu, carichi Q e quote del terrassier da soli
  non identificano puntoni. Una linea manuale contiene una quota asse.
- Livelli ordinati per quota decrescente, nominati −1, −2, −3. Non è il numero
  fisico di puntoni. Il riepilogo per coupe appare nel cantiere e nella sezione
  puntoni; non modifica quantità o avanzamento della posa già registrati.
- Il trattamento è informativo e di altra impresa. La presenza senza una quota
  accanto al testo richiede compilazione manuale del limite superiore/quota unica
  e, facoltativamente, inferiore. «Non riconosciuto» non significa «assente».

Le informazioni aggiuntive sono conservate in `SiteCoupe.drawing_info` (colonna
JSON nullable, aggiunta anche dalla migrazione di avvio). Il PDF non viene
archiviato dall'analisi: per conservarlo si usa l'archivio documenti del cantiere.
L'anteprima è temporanea nel browser, non è una nuova pianta SharePoint.
Una nuova lettura non cancella informazioni su puntoni/trattamento non riconosciute.

Verifiche: PDF sintetico con due coupe e ritaglio, testo ambiguo/scansione, ruoli,
richieste da altra origine, controllo metadati e quote, conservazione al fallimento,
salvataggio reale dal browser, riepilogo cantiere e avanzamenti preesistenti intatti.
La prova su un PDF reale dell'ingegnere rimane necessaria per verificare le sue
convenzioni grafiche. La pianta dedicata ai puntoni è fuori da questa prima fase.
