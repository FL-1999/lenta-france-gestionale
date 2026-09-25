# Supplier services and fleet

The existing supplier profile, contacts, article catalogue and purchase history remain in place. A service catalogue and an operational register are available under `/manager/servizi` to the same manager/admin roles that manage suppliers and costs.

- Services have an editable category and counting unit; they require no stock article. Rentals add a period and explicit billed quantity, following the contract rather than assuming calendar prorating.
- Catalogue prices are copied into a registration and remain editable there. Changing a catalogue price never changes existing records.
- A registration can reference a site and optionally one vehicle or machine. With no site it remains a company expense in the register. Services never change stock quantities.
- Planned records do not create actual costs or maintenance history. Executed records create/update one site economic entry and optionally appear in the asset maintenance history. A correction updates the same record. Cancellation requires a reason, removes the derived cost/history entry and retains the audited original. Review monthly invoices against these records; do not manually post the same service cost again. The material delivery invoice reconciler remains separate.
- Maintenance stores the reading and optionally the next service date/reading. It does not overwrite insurance, statutory inspection or current telemetry/odometer values. No manufacturer interval is guessed. Historical changes remain in the audit log.
- Supplier deletion is blocked when services or catalogue entries exist. Use deactivation. Site deletion detaches company service history and preserves its site-name snapshot. Vehicle deletion is blocked when service history exists.
- New `supplier_services` and `service_records` tables are included in application schema creation and database backups. No existing supplier rows or production records are migrated or modified at deployment.

Vehicle cards expose the maintenance history, existing fleet data and transport list filtered by vehicle. Creating a trip from an eligible vehicle preselects it; the existing transport availability rules still apply.

## Manual plan corners

Automatic recognition stays conservative. In geometry tools the operator may explicitly connect A/B labels of the same number, regardless of angle. This preserves both measured arms, element identifiers and source geometry, but displays/selects one production unit. The union removes shared internal edges when possible; disconnected geometry remains disconnected rather than inventing a filled bridge. Manual grouping requires explicit net-width confirmation before approval because intersection deductions cannot safely be inferred from a PDF. Existing coupe consistency and production-fiche protections still apply. Separate and undo controls remain available.

## Verification

`test_supplier_services.py`: cost lifecycle and duplicate requests, optimistic locking, permissions/CSRF, reference validation, vehicle and machine histories, supplier/site retention, manual oblique corner approval.

`test_supplier_services_live.py`: actual browser form submission, invalid rental dates preserving input, vehicle history, trip preselection, mobile fleet and manual corner save/reload.

Purchasing navigation browser coverage now expects section tabs to open their unfiltered roots while the Back link preserves the local navigation context.
