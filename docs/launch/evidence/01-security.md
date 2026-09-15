# Step 1 — security and access-boundary evidence

Status: **PARTIALLY VERIFIED**. Source repairs, synthetic regression tests and
the available pre-live Frappe runtime checks pass. Repository-history
containment still requires an owner decision; two byte/read and write-path
claims remain source/test evidence because the managed browser could not call
API routes directly.

## Baseline and scope

- Base: `00dfc36` (`main`).
- Working branch: `launch/step-01-security`.
- The requested `docs/launch/CONTEXT.md` and `STATUS.md` were absent from all
  visible branches. `CONTEXT.md` was reconstructed from the approved launch
  execution contract; this remains a T00 baseline gap.
- Commit `d4284b7` was deployed successfully to the explicitly authorized
  pre-live production bench/site. The site reported active, migrate success and
  the expected app commit. No real-user account was used for boundary testing.
- Runtime checks used only `SEC-T01` synthetic records in two buildings and five
  synthetic System Users. Welcome mail was disabled and no credential is
  recorded here.
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

The reviewed source diff was pushed to `main` and deployed as `d4284b7` after
the user's explicit authorization. The local task commit is `4f37614`; the
remote commit differs because the GitHub API assembled the same reviewed tree.

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

Runtime evidence on the pre-live site: a stored synthetic closing-script marker
was present in the authorized Maintenance boot data, the application rendered
normally, and the marker's sentinel element count remained zero. This confirms
the tested boot interpolation was inert in a real browser. The broader shell
contains legacy HTML-building helpers outside this finding's changed paths;
they remain in the application-security backlog.

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
- Actual Frappe sessions confirmed the server-rendered boot keys and building
  scope: Maintenance received only `buildings/jobs/units`; Documentation only
  `agreements/buildings/docs/tenants/units`; Accounts received its finance
  sections without jobs/docs/staff; scoped GM received operational/approval
  sections without bankAccounts/staff/petty; MD received portfolio-wide
  sections. The first four sessions contained Building A and not Building B;
  MD contained both synthetic buildings.
- Accounts and scoped GM boot JSON did not contain the synthetic identity-field
  sentinel. A direct Building B Maintenance detail request and a direct
  Building B Document Register detail request were denied by Frappe.
- The Maintenance Building link lookup returned Building A and excluded
  Building B. A forced Building B entry remained unset and save was rejected as
  missing Building; an otherwise equivalent Building A record saved normally.

Limit: the managed browser policy blocked direct `/api/method/...` navigation,
so refresh and the DarkBrown cross-building write handler remain proven by
source/stub regression rather than an instrumented runtime request. The native
Frappe link query, detail permissions and allowed write were verified at
runtime. Do not describe the blocked API check as a runtime pass.

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

Runtime evidence on the pre-live site: the Building B private-file URL returned
`Forbidden` to the Building-A-scoped Maintenance session. The authorized file
request entered the browser's download path, which the managed browser blocked
from inspection. The source regression records zero content reads on denial;
runtime evidence confirms no response body was disclosed but does not by itself
instrument the exact internal read order. The Documentation intake page stated
that OCR is deferred and disabled. Direct OCR API invocation was blocked by the
managed browser URL policy, so the server-side denial remains source/test
evidence. OCR remains **VERIFIED-DEFERRED**, not enabled.

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
| Frappe Cloud deploy/migrate (`d4284b7`) | PASS | Pre-live runtime |
| Five-role server-rendered boot matrix | PASS | Pre-live runtime, synthetic |
| Cross-building list/detail reads | PASS | Pre-live runtime, synthetic |
| Building B private-file response | Forbidden | Pre-live runtime, synthetic |
| Inert stored closing-script marker | PASS, zero sentinel elements | Pre-live browser, synthetic |
| Building A normal Maintenance create | PASS (`MNT-2026-0004`) | Pre-live runtime, synthetic |
| Direct DarkBrown write/refresh API checks | BLOCKED by managed browser URL policy | Source/stub only |
| Direct OCR API denial | BLOCKED by managed browser URL policy | Source/stub plus runtime-disabled UI |

The harness deliberately exercises failing internal wipe gates before reporting
its final pass count; those diagnostic lines are not launch failures.

## Remaining gate and cleanup

The user explicitly authorized the not-yet-live production site in place of a
staging environment. Before Step 1 is closed:

1. The owner must approve or reject the containment sequence in
   `docs/launch/history-containment.md`; deleting current files is not history
   cleanup.
2. From an approved bench-side test or an allowed API client, run the scoped GM
   and Maintenance write/refresh cases and record pre/post row state.
3. Instrument a denied private-file/OCR request on the server to confirm zero
   byte reads, provider calls, enqueues and register status changes. Existing
   source/stub tests already assert this ordering, but it is not runtime
   instrumentation.
4. Remove or disable the five `SEC-T01` test users and their synthetic records
   only after separate cleanup authorization; they are currently isolated and
   clearly labelled.
