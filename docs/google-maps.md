# Google Maps setup

## Geocoding API
La funzione "Centra su indirizzo" richiede la **Geocoding API** oltre a Places/Maps.

1. Apri Google Cloud Console e seleziona il progetto usato per `GOOGLE_MAPS_API_KEY`.
2. Vai in **API & Services** ➜ **Library**.
3. Abilita **Geocoding API**.
4. Verifica i costi/quote nella sezione **Billing**.

Se la Geocoding API non è abilitata, il bottone mostra un messaggio di errore e non centra la mappa.
