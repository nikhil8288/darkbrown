# Inventory coverage correction

Baseline: 80e369147e89cf7ff1980e903df1402965d5403b. No cleanup/posting enabled.

## Findings and changes

Four observed OperationalError cases have a reproducible field-selection defect:
Customer Group.default_receivable_account and Supplier Group.default_payable_account
are Section Breaks. Promotional Scheme.customer/supplier and Process Statement
Of Accounts.cost_center are Table MultiSelects. These are not parent SQL columns.
Inventory now excludes layout/table/virtual fields from scalar reads; child table
relationships remain in the graph and their stored rows are read separately.
Installed schema evidence is from ERPNext commit
4aee12e16c664897571457c007aaa95b8364bbbb, the JSON files under
setup/doctype/{customer_group,supplier_group} and
accounts/doctype/{promotional_scheme,process_statement_of_accounts}.

System Settings.reset_password_template is an Email Template Link, not a password.
Only this exact doctype/field/type/target gets the narrow exemption. Password
fields and other secret-name matches remain excluded.

Fifteen virtual types are classified in virtual_review.json against exact
installed upstream commits and the reviewed relationship fingerprint. They are
represented outside ordinary records with record_count=null, never a fictitious
zero count. Controllers are not executed. Unknown virtual types, changed upstream
versions and changed links still require review.

- Bulk Transaction Log aggregates stored Bulk Transaction Log Detail rows.
- Payment Reconciliation and its three child types represent transient forms;
  financial effects are recorded in native invoices/payment/ledger documents.
- Permission Inspector is a transient permissions diagnostic.
- Recorder and its two children use Redis diagnostic data, preserved outside
  business cleanup. Request/query contents are never exported.
- System Health Report and its five children are generated diagnostics. Its
  controller enqueues a ping job, so inventory must not invoke it.

Sources: frappe/frappe at 8f801ade016078685c3165c96e38f84f249f5309,
core/doctype/{permission_inspector,recorder,recorder_query,recorder_suggested_index,
rq_job,rq_worker}, desk/doctype/system_health_report and its children;
frappe/erpnext at 4aee12e16c664897571457c007aaa95b8364bbbb,
bulk_transaction/doctype/bulk_transaction_log and accounts/doctype/payment_reconciliation
and its children. The actual installed project Link on Payment Reconciliation
is included in its reviewed relationship fingerprint.

RQ Job and RQ Worker remain explicit blockers. Their runtime Redis state and a
site-scoped pause/drain procedure must be reviewed before cleanup; neither zero
jobs nor scheduler inactivity is inferred. Existing scheduler behavior is unchanged.
All original cleanup validation gates, including October cutoff, remain unchanged.

## Deploy and verify

Extract this code-only overlay at the repository root, push/deploy as usual,
then run the same Admin > Load companies > Export migration inventory flow.
Upload the fresh private JSON for review. Expected result, if there are no further
schema differences: 15 classified virtuals plus 2 queue blockers, rather than 22
unclassified errors. The old JSON is not rewritten or certified complete.

## Tests

58 synthetic Python checks passed: inventory_coverage 11,
migration_review_fixes 18, migration_preparation 20,
migration_inventory_download 9. API tests use Werkzeug plus stubbed Frappe.
No deployed SQL capture, queue inspection, cleanup lifecycle or restore test was
performed. Successful recapture is required to verify the four actual SQL reads.
