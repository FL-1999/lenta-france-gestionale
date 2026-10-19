# Compact phone directories

`mobile-directory.js` enhances explicitly marked server-rendered directories at screen widths up to 767px. `mobile-directory.css` hides the summaries on desktop and in print. Original tables, controls and links remain in the document. If JavaScript or native dialogs are unavailable, the existing responsive layout remains usable.

For a **read-only** table, add `data-mobile-directory` and zero-based column indices:

- `data-mobile-title`, optionally `data-mobile-title-selector` within that cell.
- `data-mobile-meta` and `data-mobile-labeled-meta` for concise secondary information.
- `data-mobile-status` for status badges; `data-mobile-text` can give icon-only content a readable label.
- `data-mobile-primary` selects the original detail link within a row. Without it, the title opens the detail dialog.
- `data-mobile-actions` identifies action columns. The dialog invokes the original controls, preserving event handlers, form ownership, CSRF and confirmation dialogs.
- `data-mobile-legacy` identifies an existing duplicate mobile list to hide only after enhancement succeeds.
- `data-mobile-hide-header` removes a redundant card heading on phones; do not use if that heading contains controls.

All non-action fields remain available in the detail dialog. Footer totals are included. Original row `style`/`hidden` changes are mirrored so existing client-side searches continue to work. Do not attach new search handlers to the summaries.

Card directories use `data-mobile-cards` with `data-mobile-card` items, and explicit `data-mobile-name`, `data-mobile-meta`, `data-mobile-status`, `data-mobile-field` hooks. `data-mobile-toolbar` keeps a header's existing primary link visible and puts its other actions in the phone menu.

Do **not** opt editable tables, bulk selection forms, technical drawings or attendance editors into this renderer. The warehouse's selectable rows and the personal workspace instead use scoped CSS, retaining their original controls and events. New permissions, endpoints or data writes do not belong in this presentation component.

`tests/test_mobile_directory_browser.py` covers real authentication, phone layouts, search, dialogs, original actions, warehouse reactivation, role visibility, desktop/print and no-JS fallback. Run with `RUN_BROWSER_TESTS=1`; optionally `MOBILE_BROWSER_ENGINE=webkit` for Safari's engine. Existing attendance, personnel and warehouse browser tests cover actual saves and bulk selection.
