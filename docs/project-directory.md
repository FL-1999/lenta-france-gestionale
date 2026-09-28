# Rubrica cantieri / Annuaire chantiers

Manager and admin can open `/manager/rubrica` from the site-work sidebar. Each company/contact has general details, one or more categories (MOE, MOA, gros œuvre, terrassement, other), and explicit links to existing sites. Each link has its own roles, which may differ between projects. Current site names, codes and statuses are shown on the contact detail; the site page exposes reverse links.

Categories, contacts and site associations can be edited. Archiving hides a company from the active list while retaining its details and history; it can be reactivated from the archived list. Case-insensitive normalized names prevent duplicate entries. Revision checks prevent stale edits, and saves include CSRF/origin checks and before/after audit snapshots.

Deleting a site detaches its links and preserves its latest name, code, dates and roles as history. Editing the company later retains those deleted-site snapshots. Removing a live association from the form is an explicit audited correction. This directory does not rewrite existing free-text PDF cover fields or automatically create supplier accounts. Existing projects can be linked manually, including completed projects.

The new tables participate in the existing schema bootstrap and database backup. No production contacts are seeded or inferred from existing strings.

## Rentals

In Services et locations, `Nouvel enregistrement` has a dedicated `Chantier destinataire` section, independent of vehicle/machine maintenance. A bungalow rental can have a site and no asset. The generic catalogue holds the tariff; the actual registration holds the site, period, quantity and status. Executed registrations feed site economics; planned ones remain forecasts. Reassigning the site updates the same cost entry. From a site page, the service-registration shortcut preselects the site.

## Verification

Backend tests cover rental costs and reassignment, role/CSRF restrictions, duplicate company/site validation, revision conflicts, archive/reactivation, category/search/pagination, escaped contact content and preservation through site deletion. Real-browser checks cover rental creation without a vehicle, form errors preserving input, directory creation/editing and links in both directions, French labels and mobile layout.
