# Articoli da completare

The warehouse entry remains macro → category → item. Catalog managers get an additional
**Da completare / À compléter** entry, not a stock category. It links to a paginated,
searchable list with independently selectable classification, missing supplier and missing
supplier-code filters. Each active item counts once in the total, even with several issues
or several suppliers. Archived items are excluded.

Classification requires an active category with a macro. A category without a macro links
to that category's editor; uncategorized/inactive-category items use the existing item
classification form. The existing batch classification view remains available.

An article can be saved without a supplier, or with a supplier but without its SKU.
The additive `warehouse_supplier_pending` table stores the latter association, uniquely
per supplier/item. Startup `create_all` creates the table on SQLite and PostgreSQL;
existing items and vendor-code constraints are not rewritten. No placeholder supplier
codes are inserted into the real catalog. Existing articles are evaluated on every read,
without a backfill or changes to stock, prices, movements, orders or internal codes.

Adding a real SKU from the article, completion list, or an order resolves that supplier's
pending association. Other pending suppliers remain. Reads also suppress stale pending
associations when a real code already exists, including records added by integrations.
Blank historical supplier codes can be completed through the existing code editor.
Orders with a known stock item and no SKU remember the known supplier too.

Catalog manager permissions guard the list and mutations. Existing code-conflict checks
and supplier locking remain in place; additions/removals from the item UI are audited.
Removing an erroneous pending association does not remove any real catalog code.

Tests: `test_warehouse_completion.py`, `test_warehouse_completion_live.py`, plus article
supplier, purchasing and warehouse regression suites. Browser tests use isolated fixtures
and exercise desktop and 390/320px phone widths in Italian/French and both themes.
