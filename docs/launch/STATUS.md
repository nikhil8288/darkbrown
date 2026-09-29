# DarkBrown launch status

Migration preparation (2026-09-30): private static evidence extraction and rent
preview completed; no site mutation or financial posting. Read-only inventory
export and deterministic cleanup planning added. Execution package remains
incomplete pending site inventory, remaining financial implementation and
disposable ERP integration/recovery verification. See
[migration preparation](migration-preparation.md). Do not treat this as October
operational readiness or financial sign-off.

Preparation review correction (2026-09-30): legacy check allowlist narrowed,
parent/linked-record protections enforced, and singleton-safe inventory v2
required. Focused synthetic regressions and preserved migrate/owner-nightly
checks are documented in [review evidence](evidence/migration-review-fixes.md).
Actual ERP integration and production inventory remain unavailable.

| Step | Status | Evidence | Next gate |
| --- | --- | --- | --- |
| T00 baseline | PARTIAL | Exact Frappe 15.120.1, ERPNext 15.121.2, backup status, successful deploy/migrate and active pre-live site confirmed | Confirm individual worker/scheduler state and restore proof |
| Step 1 / T01 security | PARTIALLY VERIFIED | `evidence/01-security.md` — source tests and available five-role pre-live runtime checks pass | Owner containment decision plus bench/API write, refresh, byte-read and OCR instrumentation |
| Step 2 / tenancy + accounting foundation | DEPLOYED; RUNTIME VERIFIED EXCEPT OWNER/ROLE GATES | `evidence/02-tenancy-accounting-foundation.md` — lifecycle safety code `15d9a0d` deployed; 104 source/stub checks plus synthetic tenancy, Head Lease and custom-UI lifecycle checks pass | Configure owner-approved Bank Account and run the fresh five-role new-record matrix |

## Step 1 finding disposition

| Finding | Current disposition |
| --- | --- |
| DB-01 | Current checkout/distribution repaired; BLOCKED on public history containment and owner decision |
| DB-02 | Real pre-live browser confirms the synthetic closing-script marker remains inert; broader legacy interpolation remains backlog |
| DB-03 | Five actual Frappe sessions confirm boot field/section/building scope and cross-building detail denial; direct write/refresh API runtime instrumentation remains outstanding |
| DB-20 | Scoped direct private-file request is forbidden at runtime; zero-read ordering remains source/stub evidence. OCR is server/UI disabled and VERIFIED-DEFERRED |
