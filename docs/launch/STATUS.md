# DarkBrown launch status

| Step | Status | Evidence | Next gate |
| --- | --- | --- | --- |
| T00 baseline | PARTIAL | Exact Frappe 15.120.1, ERPNext 15.121.2, backup status, successful deploy/migrate and active pre-live site confirmed | Confirm individual worker/scheduler state and restore proof |
| Step 1 / T01 security | PARTIALLY VERIFIED | `evidence/01-security.md` — source tests and available five-role pre-live runtime checks pass | Owner containment decision plus bench/API write, refresh, byte-read and OCR instrumentation |
| Step 2 / tenancy + accounting foundation | DEPLOYED; PARTIALLY RUNTIME VERIFIED | `evidence/02-tenancy-accounting-foundation.md` — code `4be2284` deployed/migrated; 99 source/stub checks plus synthetic successful tenancy/Head Lease activation and occupancy transition pass | Configure owner-approved Bank Account; prove active Head Lease overlap, post-activation zero GL, lifecycle services and five-role new-record matrix |

## Step 1 finding disposition

| Finding | Current disposition |
| --- | --- |
| DB-01 | Current checkout/distribution repaired; BLOCKED on public history containment and owner decision |
| DB-02 | Real pre-live browser confirms the synthetic closing-script marker remains inert; broader legacy interpolation remains backlog |
| DB-03 | Five actual Frappe sessions confirm boot field/section/building scope and cross-building detail denial; direct write/refresh API runtime instrumentation remains outstanding |
| DB-20 | Scoped direct private-file request is forbidden at runtime; zero-read ordering remains source/stub evidence. OCR is server/UI disabled and VERIFIED-DEFERRED |
