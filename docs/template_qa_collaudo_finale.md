# Template QA – Collaudo Finale

| Area | Test da eseguire | Esito (✅ OK / ⚠️ Minore / ❌ Bloccante) | Note | Evidenza / Screenshot | Priorità |
|---|---|---|---|---|---|
| Preparazione | Verificare ambiente di test (URL corretto, DB aggiornato, cache svuotata, account test pronti). |  |  |  | Alta |
| Preparazione | Confermare versione build/release, branch e data collaudo nel verbale QA. |  |  |  | Alta |
| Login / Logout | Login con credenziali valide (utente manager): accesso consentito e redirect corretto. |  |  |  | Alta |
| Login / Logout | Login con credenziali non valide: messaggio errore chiaro senza crash. |  |  |  | Alta |
| Login / Logout | Logout da menu: sessione chiusa e ritorno a pagina login/home pubblica. |  |  |  | Alta |
| Switch ruolo | Cambiare ruolo utente (es. manager ↔ capo/driver) e verificare menu/permessi aggiornati. |  |  |  | Alta |
| Switch ruolo | Tentare accesso a sezione non autorizzata dopo switch: blocco corretto (403 o redirect). |  |  |  | Alta |
| Dashboard manager | Verificare caricamento KPI, widget e cards principali senza errori grafici/dati nulli anomali. |  |  |  | Alta |
| Dashboard manager | Verificare filtri dashboard (data/stato/cantiere) e aggiornamento coerente dei risultati. |  |  |  | Media |
| Cantieri | Aprire lista cantieri, ricerca e filtri: risultati corretti e paginazione funzionante. |  |  |  | Alta |
| Cantieri | Creazione/modifica cantiere: salvataggio riuscito e dati persistenti al refresh. |  |  |  | Alta |
| Depositi | Aprire lista depositi e dettaglio: dati coerenti, nessun campo critico mancante. |  |  |  | Alta |
| Depositi | Inserire/aggiornare deposito (se previsto): validazioni e conferma salvataggio corrette. |  |  |  | Media |
| Trasporti | Aprire elenco trasporti/viaggi: ordinamento, filtri e stato viaggi corretti. |  |  |  | Alta |
| Trasporti | Creare nuovo trasporto/viaggio con dati validi: conferma e presenza in lista. |  |  |  | Alta |
| Modifica viaggio | Modificare viaggio esistente (data, mezzo, stato, note) e verificare salvataggio. |  |  |  | Alta |
| Modifica viaggio | Verificare gestione vincoli (campi obbligatori, formati non validi, conflitti orari). |  |  |  | Alta |
| Magazzino archiviati | Aprire sezione archiviati: elenco leggibile, filtri attivi e dati storici consistenti. |  |  |  | Media |
| Magazzino archiviati | Ripristino/consultazione record archiviato (se previsto): esito coerente con regole di business. |  |  |  | Media |
| Notifiche | Generare evento che produce notifica e verificare comparsa in UI con contenuto corretto. |  |  |  | Media |
| Notifiche | Segnare notifica come letta/non letta e verificare aggiornamento badge/contatore. |  |  |  | Bassa |
| Mappa Google Maps | Verificare caricamento mappa senza errori JS/API key e centratura iniziale corretta. |  |  |  | Alta |
| Mappa Google Maps | Verificare marker, popup e interazioni (zoom/pan/click) su dispositivi desktop. |  |  |  | Media |
| Errori 403 / 404 / 500 | Forzare route non esistente e verificare pagina 404 custom leggibile. |  |  |  | Alta |
| Errori 403 / 404 / 500 | Forzare accesso non autorizzato e verificare gestione 403 coerente. |  |  |  | Alta |
| Errori 403 / 404 / 500 | Simulare errore server (scenario controllato) e verificare pagina 500 + log tracciabile. |  |  |  | Alta |
| Go / No-Go finale | Riepilogo bloccanti aperti: se presenti ❌ → NO-GO; assenti → valutare GO. |  |  |  | Alta |
| Go / No-Go finale | Approvazione finale QA/PM con data, firma e note di rilascio. |  |  |  | Alta |
