# Descrizione dei terreni e fiche A4

Ogni strato incontrato può avere tre caratteristiche facoltative e indipendenti:
granulosità (molto fine, fine, grossolano), pezzatura (0-50, 50-100, >100 mm)
e assenza di frazione fine (Sans fines). “Ciottoli grossi / Gros cailloux” è disponibile
fra i materiali incontrati e nel modello teorico della coupe.

Le caratteristiche sono salvate nella descrizione esistente dello strato, entro
il limite di 100 caratteri, e vengono ricostruite alla riapertura della scheda.
Non è necessaria una migrazione. Gli input facoltativi dell’assistente
`strato_granulometria`, `strato_pezzatura` e `strato_fini` usano gli stessi controlli
server delle schede manager/caposquadra. Nessun cambiamento ai permessi o alla
conferma delle fiches.

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
