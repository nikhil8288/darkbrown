# Role guards on every endpoint

Repo-root overlay. **Supersedes `darkbrown_forms_staff_pettycash.zip`.** Apply
this one on top of it.

**No migrate needed.** No doctype changed, no field added.

    git pull
    bench --site <site> clear-cache
    bench --site <site> restart

Then delete the tracked `.pyc` that `.gitignore` should already have caught:

    git rm --cached darkbrown/www/managing_director_dashboard/__pycache__/index.cpython-312.pyc

## Files

New:

    darkbrown/guards.py

Changed (20): `api/agreements.py` `api/app.py` `api/approvals.py`
`api/cashdesk.py` `api/command.py` `api/doc_intake.py`
`api/doc_intake_phase2.py` `api/documents.py` `api/finance.py`
`api/md_dashboard.py` `api/number_cards.py` `api/operations.py`
`api/people.py` `api/pettycash.py` `api/portfolio.py`
`darkbrown/doctype/building/building.py` `utils/cheques.py`
`utils/collections_case.py` `utils/pdc_accounting.py` `utils/rent_invoicing.py`

127 lines added, 4 removed. Nothing was deleted or rewritten; every change is a
guard line, an import, or a comment.

---

# 1 — What was wrong

Every endpoint in this app writes through `ignore_permissions=True`, which tells
Frappe to skip the DocType permission tables. Those tables are correct — Cheque
is Accounts/GM/MD, Weekly Closing is Accounts/MD, Staff Member holds pay at
`permlevel: 1`. All of it was bypassed on every call.

Six modules had **no role check at all**: `finance.py` (13 endpoints),
`operations.py` (7), `cashdesk.py` (4), `documents.py` (4), `pettycash.py` (4),
`portfolio.py` (3), plus `number_cards.py` (10).

The only thing between a Maintenance login and `finance.record_receipt` was that
the screen did not draw the button. `/api/method/...` does not care what the
screen draws.

Four other modules did guard, in four different idioms — `admin._guard()`,
`attention._guard()`, `approvals._is_md()/_is_gm()`, `doc_intake`'s
`has_permission`. The pattern existed. It had never reached the modules that
move money.

# 2 — What this does

`darkbrown/guards.py` — role constants and one `guard(*roles)` function that
throws `PermissionError` unless the caller holds one of them. System Manager and
Administrator always pass. Called with no roles it denies everyone but those
two: a guard that fails closed is a bug report, one that fails open is an
incident.

It is a plain call at the top of each function, **not a decorator**. Frappe
introspects a whitelisted function's signature to map form arguments onto
parameters, and wrapping changes what that introspection sees. A first line in
the body cannot break argument passing, and it greps.

**82 guards added across 106 whitelisted endpoints.** The other 24 already had a
real check and were left alone.

## Where the role sets come from

Not invented. Read off the DocType permission JSON. An endpoint that writes a
record gets the roles that DocType grants write or create to; an endpoint that
reads gets the read set. If a guard looks wrong, the DocType table is where the
argument is, and changing it there is the fix.

Worked examples:

| Endpoint | Guard | From |
|---|---|---|
| `finance.record_receipt` | MD, ACC | Cheque: MD RWCD, ACC RWCD, GM **R** only |
| `finance.build_invoice_run` | MD, GM, ACC | Invoice Run: MD, GM RWC, ACC RWCD |
| `pettycash.record_entry` | MD, GM, ACC | Petty Cash Entry grants GM **create** |
| `pettycash.record_count` | MD, ACC | ...but not **write**, and an adjustment is a write |
| `portfolio.set_unit_status` | MD, GM, MNT | Unit: MNT has RW - readiness is their job |
| `portfolio.onboard_building` | MD, GM | Building: MNT and ACC are read-only |
| `operations.raise_job` | MD, GM, MNT | Maintenance Request: MNT RWCD, ACC **R** |
| `people.save_staff` | MD, ACC | Staff Member: GM is **R** only |

Three endpoints are open to all five roles on purpose: `app.refresh` (the boot
payload, already role-filtered inside), `number_cards.vacant_units` and
`occupancy_pct` (portfolio counts every role's own screen already shows them).

# 3 — Three bugs the sweep found

Not introduced here. Found by looking at all 106 at once rather than one at a
time.

**`decide_amendment` could be approved by anyone.** The reserved-category check
only fired when status was `Pending MD`. An amendment sitting at `Pending GM`
had no check at all - a Maintenance login could approve a rent change. Now
guarded MD/GM at entry, with the stricter MD rule for `Pending MD` intact.

**`charts.py` has never once run.** It does
`from darkbrown.utils.rent_invoicing import GENERATION_START`, and that constant
lives in `api/md_dashboard.py`. The module raised `ImportError` on load, so all
three endpoints - including `get_projection`, **the 12-month projection the D80
work went into** - were dead on arrival. The constant now lives in
`rent_invoicing.py`, where charts already expected it and where it belongs; it
is the date invoice generation begins, not a dashboard setting. `md_dashboard`
re-exports it so the two cannot drift.

**A second V1 doctype name.** `PDC Cheque` - 60 references across 11 files,
including `attention.py` and `charts.py`, which are both live. That is larger
than the `Tenant Rental Agreement` problem and belongs with it in the next
batch.

# 4 — On `ignore_permissions`, and what is still open

113 occurrences app-wide. They are **not removed**, deliberately:

- ~30 are in `patches/`, `demo/` and `install.py`, which run as Administrator
  during migrate or seed. Correct as they are.
- 12 target ERPNext records - Sales Invoice, Payment Entry, Cost Center,
  Customer, Supplier, File. DarkBrown's five roles hold no ERPNext accounts
  permissions **by design**, so removing these would break every posting.
- The rest target DarkBrown's own doctypes. Behind a guard these are now
  redundancy rather than a hole, and stripping them cannot be tested without a
  real database. That is a separate, testable change.

**One gap the guard does not close.** `ignore_permissions=True` also bypasses
`permission_query_conditions`, which is how `permissions.py` restricts a General
Manager to their assigned buildings. A GM scoped to three buildings can still
act on all twenty-two through these endpoints. The guard says *which role*, not
*which buildings*. If GM scoping is meant to bite, that needs its own pass.

# 5 — Tested, and not

The harness imports the **real shipped modules** against a stubbed Frappe - not
a replica of the logic - and calls all 106 endpoints once per role, with a stub
that raises if anything reaches the database.

- All 106 modules import cleanly. Before this batch, three did not.
- **Zero endpoints reachable by a user holding no DarkBrown role.** Before: 67.
- Every endpoint's allowed-role set matches the table in §2.
- Every module imports every constant it uses (checked by AST, after this
  exact bug slipped through the first pass).
- Whole app byte-compiles.

**Not verified:** anything against a real database. The guard is pure addition
and cannot change what a permitted call does, but the role sets are a judgement
about who should be doing what, and they are worth ten minutes of you reading
the table in §2. If Fatima needs to log a cheque and cannot, that table is why.
