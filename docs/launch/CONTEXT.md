# DarkBrown launch execution context

This file was absent from repository commit `00dfc36`. It is established here
from the approved launch-plan execution contract so later tasks have a local
source of truth.

## Working rules

- Work on an isolated task branch and preserve unrelated user changes.
- Reproduce only the named findings, make the smallest coherent repair, and
  record real evidence. An audit is a reproduction guide, not runtime proof.
- Use synthetic data on disposable staging. Keep external mail, bank/payment,
  OCR/extraction and other real integrations off or mocked.
- Never place real identities, financial details, credentials or operational
  imports in Git, logs, fixtures or evidence.
- Use native Frappe/ERPNext permission and transaction behavior. UI visibility
  is not authorization.
- Source/stub tests remain labelled as such until the same behavior is proven
  on the configured Frappe/ERPNext staging baseline.
- Production deployment, destructive cleanup, repository visibility changes,
  history rewriting and external communications need explicit authorization.
- A finding closes only as fixed with regression evidence, disproved with
  current runtime evidence, or verified-deferred with the feature denied at
  both server and interface.

## Current environment

- Repository baseline: `00dfc36` on `main`.
- Task branch: `launch/step-01-security`.
- Runtime: source checkout only; no bench, staging site, workers or database
  are available in this workspace.
- Fast verification: `verify/harness.py`, `verify/files_api.py`,
  `verify/notes_api.py`, and `verify/security_boundaries.py`.
