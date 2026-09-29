# Browser inventory download

Baseline: `184c92c1c61f2a141b58d47fa8d99f8987116de6`.
This update adds a browser alternative to the existing bench export.

## Deploy and use

1. Extract the overlay ZIP at the repository root, preserving its directories.
2. Commit/push the changed files to `main` and deploy through Frappe Cloud.
3. Sign in to `https://erp.darkbrown.qa/darkbrown#/admin` as the actual
   **Administrator** account. An MD/System Manager role on another user is
   intentionally insufficient. Refresh with Ctrl+Shift+R after deployment.
4. In **Migration inventory**, click **Load companies**, select the actual
   Company (a sole company is selected automatically), then click
   **Export migration inventory**. Keep the page open until it completes.
5. Download `darkbrown-migration-inventory.json` and share it privately with the
   migration reviewer. Do not add it to GitHub. Review any reported inventory
   issues; an export with errors is evidence, not a complete cleanup plan.

The site name is obtained from the server, not inferred from the custom domain.
The export includes installed app revisions, exact Company names, configuration,
record relationships, counts and v2 snapshot checksum. It is a fresh capture,
not a download of a previous server export. Repeated runs do not create ERP
records. A timeout or failed response does not produce a completed download;
report the displayed error before changing the implementation.

## Boundaries

Both endpoints are POST-only, use Frappe's normal session/CSRF handling and check
`frappe.session.user == "Administrator"` before reading. The UI flag is only
for visibility. The download reuses the reviewed `capture()` site/company
validation and field exclusions. JSON is returned directly as a no-store
attachment: no File document, public URL, filesystem path parameter or stored
server export is created. No business/configuration records are changed by this
feature. Normal framework request/session handling still applies.

No cleanup or financial posting is enabled. No schema or deployment hooks are
added. Existing configuration migrations and scheduled owner billing are unchanged.
A snapshot does not pause concurrent writes or replace backup/restore testing.

## Verification

53 Python synthetic checks passed:
- `python verify/migration_inventory_download.py` — 7; needs Werkzeug (already
  supplied by Frappe; locally tested with Werkzeug 3.1.9 and stubbed Frappe).
- `python verify/security_boundaries.py` — 8.
- `python verify/migration_review_fixes.py` — 18.
- `python verify/migration_preparation.py` — 20.

`node verify/migration_inventory_ui.js` passed visibility, company selection,
CSRF/site binding, download, server-error and non-download response checks using
synthetic DOM/fetch. Full shell JavaScript syntax and `git diff --check` passed.
The Frappe handler at the installed source revision `8f801ad` was checked to
accept returned Werkzeug Response objects. No actual ERP integration or browser
runtime test occurred; verify the first download after deployment.
