# Piano implementazione - Acquisti > Nuovo ordine

## File e responsabilità
- `models/__init__.py`: estensione modelli `Supplier`, `PurchaseOrder`, nuovo `Depot`.
- `migrations/044_add_order_email_wizard_fields.sql`: migrazione colonne + tabella depots + seed predefinito.
- `routes/ordini.py`: API supplier/order/email preview, rendering pagina wizard email, logica template multilingua.
- `templates/manager/ordini/ordini_new.html`: UX nuova pagina ordine con card read-only dati fornitore, blocchi Fornitore/Ordine/Consegna/Email.
- `templates/manager/ordini/email_wizard.html`: sotto-pagina wizard con preview editabile e azioni mailto/copia.

## Fasi
1. **Data model**: aggiungere campi di contatto fornitore e override ordine.
2. **Persistenza**: migrazione SQL idempotente e seed 3 depositi.
3. **Backend API**:
   - GET supplier by id
   - POST create ordine
   - POST preview email
4. **Frontend Nuovo Ordine**:
   - preload dati fornitore via API
   - card read-only + stati loading/error/empty
   - campo referente modificabile per singolo ordine
5. **Wizard email**:
   - selezione lingua IT/FR/EN
   - destinazione consegna (cantiere/deposito/ritiro)
   - destinatario default da referente email -> supplier email
   - editing subject/body e output mailto/copia
6. **QA**: test backend + smoke template.
