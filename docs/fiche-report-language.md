# Lingua delle fiches

La lingua del documento è separata dalla lingua dell'interfaccia. In assenza
di una scelta esplicita il documento è sempre francese, anche con il gestionale
in italiano. Il selettore «Lingua fiche / PDF» è disponibile nel dettaglio,
nell'elenco del cantiere e nella sezione fiches della pagina cantiere.

La scelta usa una richiesta GET `report_lang=fr|it`. Aggiorna anteprima, stampa
browser, PDF singolo e dossier completo (copertina inclusa). Non modifica la
fiche, la conferma, le quote, i volumi o la lingua del profilo. I nomi dei PDF
terminano con `_FR.pdf` o `_IT.pdf`; l'archivio mantiene le normali versioni.

Le intestazioni, i diagrammi, le firme, la curva di getto e gli allegati usano
lo stesso dizionario di traduzioni. I materiali e le caratteristiche standard
sono tradotti mediante un vocabolario tecnico. Nomi, sigle e osservazioni
libere restano come inseriti; non viene effettuata una traduzione AI.
Quando presente, la curva di getto ha un allegato A4 dedicato per evitare
sovrapposizioni con il disegno e le quote della fiche principale.

Nessuna migrazione del database o modifica ai permessi di esportazione.
I test verificano indipendenza dalla lingua UI, dati invariati, autorizzazioni,
filtri conservati, selezione mobile e PDF A4 in entrambe le lingue.
