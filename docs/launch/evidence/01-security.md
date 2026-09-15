# Step 1 — security and access-boundary evidence

Status: **BLOCKED**. Source repairs and synthetic tests pass; repository-history
containment and staging runtime verification are outstanding.

## Baseline and scope

- Base: `00dfc36` (`main`).
- Working branch: `launch/step-01-security`.
- The requested `docs/launch/CONTEXT.md` and `STATUS.md` were absent from all
  visible branches. `CONTEXT.md` was reconstructed from the approved launch
  execution contract; this remains a T00 baseline gap.
- No production site, bench, database, workers or real users were accessed.
- No repository history or visibility setting was changed.

## Narrow diff retained for review

- Authorization and boot boundary: `renderer.py`, `permissions.py`, `hooks.py`
  and `api/app.py`.
- Affected list/detail/write/file paths: `api/doc_intake.py`,
  `api/documents.py`, `api/portfolio.py`, `api/operations.py`,
  `api/agreements.py` and `api/finance.py`.
- Deferred interface controls: `shell/index.html` and `www/doc-intake.html`.
- Data containment: loader selection, ignore rules, the thirteen replacement
  CSV fixtures, their manifest and the deterministic synthetic-data generator.
- Verification/launch record: stub support, four verification scripts and the
  files under `docs/launch/`.

The changes remain local and uncommitted on `launch/step-01-security` for owner
review. Nothing was pushed, published, deployed or staged against a live site.

## DB-01 — tracked operational data

Confirmed without reproducing identity or financial values:

- The repository is public.
- Thirteen tracked loader CSVs held operational-scale records at the base
  commit; twelve historical commits touch the loader-data set.
- All thirteen CSVs now contain only a coherent two-building synthetic fixture.
- The fixture generator uses unmistakable synthetic names, reserved
  `example.invalid` addresses, non-routable contacts and synthetic references.
- `darkbrown.load.common` defaults to bundled synthetic data. Operational data
  requires `DARKBROWN_IMPORT_DATA_DIR` or the equivalent site configuration,
  and the configured path is rejected if it is inside the installed app.
- Repository-local operational import directories are ignored.
- A wheel built from the changed tree contained only the thirteen small
  synthetic CSVs and no configured private import directory, environment file
  or site configuration.

Unresolved exposure: prior Git objects and any existing clones, caches or
artifacts. The unexecuted owner-review action and rollback are in
`docs/launch/history-containment.md`.

## DB-02 — HTML/script safety

- Boot values are serialized with HTML delimiters, ampersand and JavaScript
  line separators escaped before insertion into the script element.
- A synthetic closing-script marker parses as one script element and does not
  remain as an HTML closing delimiter.
- The document-intake CSRF value moved to an HTML-escaped meta attribute.
- Stored queue, extraction-note, statement, validation and result text in the
  intake page is HTML-escaped; file previews are created through DOM properties
  and accept only local file paths.
- Both changed inline application scripts pass `node --check`.

Limit: real-browser CSP and DOM execution tests require staging and remain
BLOCKED. The broader shell contains legacy HTML-building helpers outside this
finding's changed paths; they should remain in the application-security backlog.

## DB-03 — role, field and building scope

An explicit server-side boot/refresh matrix now provides:

| Role | Boot sections |
| --- | --- |
| Maintenance | Buildings, units, maintenance jobs |
| Documentation | Buildings, units, tenants, agreements, documents |
| Accounts | Authorized portfolio/tenant finance, receipts support, bank accounts and petty cash; no staff/jobs/document-review seed |
| General Manager | Operational and approval data in authorized buildings; no bank-account, staff, petty-cash or portfolio-wide aggregate seed |
| Managing Director / System Manager | Portfolio-wide sections |

- Explicit Building User Permissions are applied to boot/refresh rows and
  totals, linked tenant/agreement/document records, private-file metadata and
  affected writes.
- Role-specific field filtering removes identity-document values from Accounts
  and GM boot data, and removes landlord contact/bank plus cheque instrument
  fields from GM boot data. Maintenance and Documentation receive no finance
  sections; Accounts receives no staff, maintenance or document-review seed.
- Permission-query hooks now cover Building, Unit, Document Register, Document
  Archive, Tenancy Agreement, Maintenance Request, Collection Case, Move Out
  Case and Invoice Run.
- Direct portfolio, maintenance, collection, move-out, tenancy/amendment,
  invoice-run, cheque, receipt, deposit and document paths call the shared
  record/building checks before reading or mutating affected records.
- Synthetic tests prove a GM scoped to Building A receives only its row/total,
  and a Maintenance write to Building B is denied before mutation while the
  equivalent Building A workflow still saves.

Limit: these are source/stub results. Real Frappe User Permission interaction,
DocType permissions and every production route require the five-role staging
matrix before DB-03 can close.

## DB-20 — private files and deferred OCR

- `require_file_access` checks native File read permission and the attached
  record's native/building permission before returning the File document.
- Extraction resolves authorization before `get_content`, status mutation or
  provider invocation. The fallback rasterizer reuses the already-authorized
  File document.
- Manual filing and preview validate the target building, source File and
  attached record before returning a URL or creating a register entry.
- OCR/extraction endpoints fail closed with a server-side release flag, and OCR
  controls/routes are disabled in both interfaces.
- A synthetic denial test records zero content reads; an authorized private
  synthetic image follows the normal byte-read path once.

Limit: Frappe's native `/private/files/...` response must be tested separately
on staging to prove denial occurs before response bytes are streamed. OCR is
**VERIFIED-DEFERRED** at source/server/UI level, not enabled.

## Executed checks

| Check | Result | Evidence class |
| --- | --- | --- |
| `verify/security_boundaries.py` | 8 passed | Synthetic source/stub |
| `verify/harness.py` | 48 passed, 0 failed | Existing source/stub regression |
| `verify/files_api.py` | 19 passed, 0 failed | Existing source/stub regression |
| `verify/notes_api.py` | 11 passed, 0 failed | Existing source/stub regression |
| Python compile | PASS | Static |
| Shell and intake inline JS syntax | PASS | Static |
| Synthetic loader manifest | PASS, 13 files | Static/content classification |
| Built wheel content audit | PASS | Distribution |

The harness deliberately exercises failing internal wipe gates before reporting
its final pass count; those diagnostic lines are not launch failures.

## Required staging gate

On disposable staging, create two synthetic buildings and users for
Maintenance, Documentation, Accounts, Building-A-scoped GM and MD. With
external delivery/payment/OCR providers mocked or off, verify:

1. Boot and refresh response keys, fields, rows and totals match the matrix.
2. Building-A GM list/detail/write requests for Building B return permission
   errors and no database mutation.
3. Maintenance and Documentation cannot call hidden finance/staff endpoints or
   retrieve forbidden sensitive fields.
4. A stored inert closing-script marker renders as text in a real browser and
   creates no additional script element or audit marker execution.
5. An unauthorized private-file URL fails both preview and direct download
   before bytes are returned; the authorized equivalent renders normally.
6. Every OCR endpoint remains denied and causes no File read, provider call,
   enqueue or Document Register status change.

Exact blocker: no configured Frappe/ERPNext staging site is available in this
workspace.
