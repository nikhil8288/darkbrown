# DarkBrown launch status

| Step | Status | Evidence | Next gate |
| --- | --- | --- | --- |
| T00 baseline | BLOCKED | `CONTEXT.md` reconstructed because the requested launch files were absent from all visible repository branches | Confirm deployed SHA, exact Frappe/ERPNext versions, staging access, workers and backup/restore proof |
| Step 1 / T01 security | BLOCKED | `evidence/01-security.md` — source repairs and synthetic tests pass | Owner containment decision plus real staging role, browser and private-download tests |

## Step 1 finding disposition

| Finding | Current disposition |
| --- | --- |
| DB-01 | Current checkout/distribution repaired; BLOCKED on public history containment and owner decision |
| DB-02 | Source repair passes inert serialization/static tests; BLOCKED on real-browser staging validation |
| DB-03 | Role/field matrix and explicit building boundary implemented; BLOCKED on real-Frappe staging validation |
| DB-20 | File/attachment checks precede byte reads and OCR is server/UI disabled; VERIFIED-DEFERRED for OCR, but private-download runtime behavior remains BLOCKED |
