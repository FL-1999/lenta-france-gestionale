# Descrizione dei terreni e fiche A4

Ogni strato incontrato ha un unico elenco facoltativo: nessuna descrizione,
molto fine, fine, grossolano, 0-50 mm, 50-100 mm, >100 mm, senza frazione fine
(Sans fines), oppure Altro con testo libero. Il materiale resta separato.
“Ciottoli grossi / Gros cailloux” è disponibile
fra i materiali incontrati e nel modello teorico della coupe.

La descrizione è salvata nel materiale esistente dello strato, entro il limite
complessivo di 100 caratteri. Le precedenti combinazioni di caratteristiche
vengono mostrate come Altro con il testo completo, senza migrazioni o perdita di dati.
Gli input `strato_descrizione` e `strato_descrizione_altro` usano gli stessi
controlli server nelle schede manager/caposquadra e nell’assistente.
Gli input precedenti `strato_granulometria`, `strato_pezzatura` e `strato_fini`
restano compatibili; il nuovo elenco, se inviato, ha precedenza, anche per
cancellare esplicitamente una descrizione. Nessun cambiamento ai permessi o
alla conferma delle fiches.

La descrizione stampata espone profondità e quote calcolate come
`quota_partenza - profondità`; il confronto usa una scala comune e distingue
quote mancanti, zero e negative. I dati di coupe già congelati nella fiche
continuano a essere la fonte delle quote. Il riferimento altimetrico configurato
(NGF, NGM...) viene conservato.

Anteprima, stampa browser e PDF usano lo stesso foglio di stile. La fiche ordinaria
resta su una pagina A4 con riquadro firme chiuso. Oltre sei strati complessivi tra
incontrati e teorici, o oltre 300 caratteri di osservazioni, i dettagli vanno
in un allegato A4, richiamato nel foglio principale. Nessun dato è tagliato
per farlo entrare nella pagina.

I collaudi coprono salvataggio/modifica, campi Altro nelle righe successive,
validazione, traduzioni, manager e caposquadra, telefono, stampa e PDF A4,
anche con allegato e con un riferimento altimetrico diverso da NGF.

La paratia, i muretti guida, le quote dimensionali e le colonne dei terreni sono
contenuti in un unico disegno SVG trasparente. La faccia della paratia e le colonne
condividono inizio e fondo, anche dopo il ridimensionamento A4. Le etichette superiori
hanno uno spazio dedicato. I controlli verificano allineamento e assenza di
sovrapposizioni in anteprima e stampa, e conservazione dei testi anche nel motore
PDF di riserva WeasyPrint disponibile su Linux.
