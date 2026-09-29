# Historical migration preparation

This is a preparation release, **not a completed migration or October readiness
certification**. No production database was connected, modified, cleaned or
posted during preparation. No push or deployment was performed.

## Baseline and scope

Verified remote: `https://github.com/nikhil8288/darkbrown.git`.
Initial branch: `main`, clean. Baseline:
`6a47950f94db5011630dd00c7cb3611cbfc983fb`.
Preparation branch: `codex/migration-preparation`.

Replacement release: see [focused review fixes](evidence/migration-review-fixes.md).
It closes the three preparation defects with synthetic regression coverage.
Cleanup requires a fresh version-2 inventory; older exports are rejected.

The user identified `erp.darkbrown.qa` as the production domain. The exact
Company record and bench site identifier still need the read-only inventory.
Earlier launch documents record versions; those are not a fresh site check.

Implemented:

- Verified source-pack checksums before sparse workbook extraction, preserving
  exact worksheet names, coordinates, formula caches, errors and blank values.
- Private rent-event preview with stable economic keys, exact contract joins,
  explicit unresolved rows, source supersession comparison and revision plans.
- Independent rent-source totals and bank-review arithmetic checks. Bank review
  rows are never treated as extra posting sources.
- Administrator-only, non-whitelisted site inventory including installed versions,
  schema links, company choices, fiscal settings, record IDs and fingerprints.
- Pure cleanup-plan validation: protected setup, explicit row decisions,
  cross-company/post-cutover rejection, retained incoming links, checksums and
  approval binding. It has **no deletion executor**.
- Removed landlord financial posting from `after_migrate`. Existing setup
  helpers still run; their current configuration behavior is unchanged.
- Disabled legacy Data API writes and queued legacy write jobs. Old bench loader
  modules remain in the repository for historical compatibility and MUST NOT be
  used for this migration. No new reset endpoint or destructive hook exists.
- Updated stale test fixtures/assertions to the role matrix and UI already present
  at baseline; fixed Windows module-name conversion in the verification harness.
  Production authorization code and financial account classifications were not changed.

## Run the private evidence preparation

From the repository root with Python 3.10–3.13:

```text
python -m darkbrown.migration.evidence <private-pack-directory> --output <new-private-output-directory>
python -m darkbrown.migration.prepare <private-pack-directory> <private-output-directory>
```

Output directories must be outside every Git repository. Extraction requires an
empty output directory and verifies every manifest hash. A second preparation run
produces a change plan with no additional events when inputs are identical.
This is deterministic planning, not an ERP importer/resume test.

Never publish source data, output JSON, bank statements, identity material or
private review logs. The deployment archive contains only the listed code,
synthetic tests and this document, retaining repository-relative paths.

## Read-only production inventory using Frappe Cloud access

For the browser alternative, see [Administrator inventory download](inventory-download.md).
It produces the same v2 snapshot without SSH; the bench commands below remain supported.

The user pushes/deploys. After deploying this preparation release, open the
site's available SSH/bench terminal. Use the actual bench site identifier shown
by the hosting environment; a custom domain may differ. If your Frappe Cloud
plan provides no terminal, ask its support/operator to execute this command.
Do not paste credentials into chat or a repository.

In Frappe Cloud, open the site serving `erp.darkbrown.qa`, follow its Bench Group,
and use that group's SSH access instructions. Connect from your terminal using
the command/certificate issued by Cloud. Run the commands below **inside the
bench directory on that remote bench**, containing `apps/` and `sites/`; not
in the browser console, Desk System Console or local PowerShell. Check
`bench list-sites` against the site's Cloud details to obtain the exact site
identifier. Cloud documents SSH access for private bench groups; if unavailable,
have the Cloud operator/support run this read-only export on the site's bench.
[Frappe Cloud SSH instructions](https://docs.frappe.io/cloud/benches/ssh).

```sh
bench --site <actual-site-name> execute darkbrown.migration.inventory.export \
  --kwargs '{"expected_site":"<actual-site-name>","output_name":"migration-inventory-01.json"}'
```

The command requires the Administrator session established by bench. It lists
actual Company names and saves a private JSON under
`sites/<actual-site-name>/private/migration-review/`. It does not insert a File
record, publish a download link, send notifications, pause jobs, or change ERP
records. Its only write is that private filesystem export. Retrieve it through
your authorized file/SSH access and store it with the private migration pack.

Then repeat with the exact company selected from that output, using a new name:

```sh
bench --site <actual-site-name> execute darkbrown.migration.inventory.export \
  --kwargs '{"expected_site":"<actual-site-name>","company":"<exact Company record>","output_name":"migration-inventory-02.json"}'
```

The inventory conservatively includes references from other installed apps.
Unreadable/virtual tables are explicit errors, not zero counts. They must be
resolved or given a reviewed adapter before exact cleanup planning. Production
counts cannot be inferred from repository fixtures. Inventory does not pause
writes; it is not itself a consistent backup or proof that the site stayed idle.

Return the command's JSON result (`company_names`, private path, SHA-256,
doctype/error counts), the exact selected Company name, and the second private
JSON export through the private attachment channel. Do not return credentials,
`site_config.json`, encryption keys or backups in chat. Keep the export out of
the public repository. A nonzero unreadable-doctype count is a blocker requiring
review, not permission to omit that table. Singleton values now participate in
dependency checks and snapshot fingerprints; secret fields remain excluded.

## Push/deploy the preparation code

Review the branch diff and extract the overlay ZIP **at the repository root**,
not inside `darkbrown/` and not with paths flattened. Commit reviewed changes
and merge them into deployment branch `main` using your normal process. Push
and deploy yourself. No financial execution command is included in this release.
Existing daily financial jobs still exist: before any eventual cleanup/import,
pause and drain jobs through the reviewed runbook below.

Local verification commands (UTF-8 is necessary on Windows):

```text
python -X utf8 verify/migration_preparation.py
python -X utf8 verify/migration_review_fixes.py
python -X utf8 verify/harness.py
python -X utf8 verify/finance_audit_fixes.py
python -X utf8 verify/security_boundaries.py
python -X utf8 verify/files_api.py
python -X utf8 verify/notes_api.py
python -X utf8 verify/tenancy_foundation.py
python -X utf8 verify/head_lease_foundation.py
```

These are source/stub and pure-Python checks. None proves actual SQL locking,
ERP posting, invoice outstanding amounts, GL/PLE reconciliation or restoration.

## Disposable accounting rehearsal proposal

Simplest proposal for this Windows machine: use a disposable Ubuntu VM with
Docker Engine, Docker Compose v2 and Git, then the official `frappe_docker`
development Compose environment. This bundles the bench, MariaDB and Redis and
avoids a hosted staging subscription. Allow 4 CPUs, 8 GB RAM and at least 60 GB
disk as a starting allocation; backup sizes may require more. Windows needs a
VM platform/virtualization enabled; alternatively use WSL2 and Docker Desktop
Linux containers. Neither environment is currently installed or configured here.

The official development setup requires selecting `version-15` explicitly
(current examples also show v16). Pin container versions and match the installed
Frappe/ERPNext commits from the inventory,
plus this app branch. Use a new test-only site, fake email, synthetic companies,
two buildings and parties, and block external email, bank, OCR and payment
integrations. Do not point tests at production, even with rollback enabled.
No disposable environment is currently confirmed; no integration result is claimed.

Required access: permission to install/run the VM or Docker, download containers
and the app repositories, bench Administrator access on the disposable site,
and authorized private access to database/public/private-file backups for the
separate restoration test. Transfer any required encryption key directly into
the isolated environment; never into chat, source control or test logs. Disable
schedulers/outbound integrations before starting workers on a restored site.
[Official development container setup](https://github.com/frappe/frappe_docker/blob/main/docs/05-development/04-alternate-setup.md).

Required tests before execution: cleanup dependency order and preservation,
invoice/owner bill GL, linked partial/full payments, advances/deposits, card and
cheque receipt/deposit/bank clearance, invoice-linked corrections, non-bank
historical clearing, subsequent bank matching without a second economic event,
period/termination/quarterly terms, concurrent billing, interruption/resume,
revised-source detection, report/GL/PLE equality and access/file boundaries.

Upstream v15 Payment Entry calls native GL and outstanding-balance workflows on
submit/cancel; this is reference evidence, not installed-version validation:
[ERPNext Payment Entry source](https://github.com/frappe/erpnext/blob/version-15/erpnext/accounts/doctype/payment_entry/payment_entry.py).
Do not label historical clearing as Cash to satisfy a payment builder. Test the
actual installed rules; if incompatible, implement an invoice-linked Journal
Entry plus internal migration receipt representation and test PLE/outstanding.

## Recovery and execution gates — not yet executable

1. Finish source-to-party/account mapping and canonical owner/expense/payroll/
   asset/settlement events. Apply source authority and recognition timing, not
   management allocations as duplicate GL expenses. Keep September provisional.
2. Complete the installed schema relationship inventory. Review every deletion
   ID and preserved/shared record. Use supported installed lifecycle facilities;
   cancellation alone does not prove ledger removal. No blanket integrity bypass.
3. Implement/rehearse the executor, private lock/checkpoint audit and dependency
   ordering on the disposable site. Keep all post-cutover records outside cleanup.
4. Capture original scheduler/notification configuration. Pause billing, queue
   producers, consumers and integrations as appropriate, drain in-flight jobs,
   and establish a maintenance window before taking the approval snapshot.
5. Take complete database, public-files and private-files backups using the
   installed bench facilities. Securely preserve site encryption/configuration
   needed for recovery. Check hashes and restore to an isolated site; verify login,
   file retrieval, ledger reports and record counts. Record exact recovery steps.
6. Review target site/company, pack/code/plan/inventory checksums, exact counts,
   expected postings, clearing schedules, reconciliation differences and recovery
   evidence. Obtain explicit execution approval only for that concrete package.
7. Re-inventory with writes quiesced immediately before execution. Any change
   invalidates the plan. Keep all migration notifications off; restore original
   settings only after verification and disable the one-time execution capability.
8. On failure, stop writes and use the rehearsed recovery path. Once new live
   transactions resume, restoring the pre-migration backup would discard them:
   preserve/replay approved new transactions or use audited forward correction.

## Outstanding implementation and evidence

This release does not implement full historical posting, cleanup execution,
checkpoint/resume, automatic tenant billing, recognition deferrals, an authorized
adjustment register or replacement of historical dashboard summaries by GL.
The existing owner billing and cheque workflows are preserved, but remain subject
to the required integration tests and agreement-term review. Exact production
deletion/preservation counts, final posting totals, backup recovery, installed
versions and financial sign-off are unavailable until site evidence is supplied.

Do not request production execution approval from this package yet. Continue
from the private progress report and the inventory rather than repeating extraction
or the earlier security audit. The user's confirmed migration decisions remain
authoritative; only genuinely unresolved facts should be requested.
