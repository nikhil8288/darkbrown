# DEPLOY — cutover readiness (supersedes the previous zip)

Overlay unpacks over the repo root. **Replaces** `darkbrown_cheque_consolidation.zip`
— it contains everything that was in it, plus the data-loading work.
Baseline: commit `d2b5bc1` (11 Aug 2026). 39 files: 5 new, 34 changed.

`bench migrate` is required — DBR Settings gains a field, twelve doctypes
change permissions, and eight patches become registered.

---

## Before you unpack — please read

While I was working, seventeen files were written into my working directory by
something other than me: a tenancy importer, a rewritten `rent_invoicing.py`,
permission edits across twelve doctypes, and later my own test harness. You
confirmed none of it was you.

**None of that code is in this zip.** I deleted the working tree, rebuilt from a
fresh `git clone`, re-applied only my own verified overlay, and wrote everything
here from the doctype schema. My test harness was restored from a known-good
copy taken before the first foreign write, then re-extended by hand.

Some of what appeared was, on inspection, correct. That is not the point — I
can't put a verified label on code I can't account for, least of all code that
writes ~250 agreements into a live ledger. Worth finding out what has write
access to that environment before you run anything against `erp.darkbrown.qa`.

---

## 1. Unpack, delete, deploy

```bash
cd ~/frappe-bench/apps/darkbrown
git status --porcelain        # should be clean; investigate anything unexpected
unzip -o darkbrown_cutover.zip

# An overlay cannot delete. These go by hand.
git rm -r darkbrown/www/managing_director_dashboard   # legacy MD dashboard
git rm index.html                                     # third front-end copy
git rm fixes_1_to_6.patch                             # stale artefact
git rm DELETE_THESE.txt                               # superseded by this file
git rm darkbrown/patches/run_july_billing.py          # see below

git add -A && git commit -m "Cutover readiness: one cheque engine, safe seeders, tenancy importer"
git push

cd ~/frappe-bench
bench --site erp.darkbrown.qa migrate
bench build && bench --site erp.darkbrown.qa clear-cache && bench restart
```

`run_july_billing.py` is shipped **disabled** — it now refuses instead of
billing — so the site is safe if you forget the `git rm`. Delete it anyway.

## 2. Configure the one new setting

DBR Settings → **Returned Cheque Charge Account**. Blank is safe: the charge is
skipped and reported as `charge_unbooked` rather than silently lost. Until it is
set, returned-cheque bank charges still do not reach the P&L.

---

## 3. Loading the real data

Three importers, all `bench execute` only, all with a `dry_run` that must come
back clean first. **None of them is registered in `patches.txt`** — a patch runs
unattended during a deploy, and these write business records.

Load in this order. Each depends on the one before.

### 3a. Tenancy book (~250 agreements) — new in this drop

```bash
cd ~/frappe-bench
bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.template
```

That prints the exact column contract. Build `darkbrown/patches/tenancies.csv`
to match it:

```
tenant_name, tenant_id, building, unit_no, unit, start_date, end_date,
monthly_rent, security_deposit, payment_mode, payment_frequency, cheques_held,
status, notice_days, auto_renew, qid_number, qid_expiry, passport_no,
mobile_no, notes
```

Only `tenant_name` (or `tenant_id`), the unit, both dates and `monthly_rent`
are required. `tenancy_charges.csv` is optional — recurring charges beyond rent,
joined on `building + unit_no + start_date`.

```bash
bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.dry_run
# resolve everything it refuses, then:
bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.run
```

**It aborts rather than guesses.** Any unmatched tenant, unmatched unit,
ambiguous name, end date on or before its start, duplicate `(unit, start_date)`
inside the CSV, or a second live tenancy landing on a unit that already has one
— and nothing is created. It never auto-creates a Customer. Unmatched names go
in `tenancy_name_map.csv`, which `dry_run` prints paste-ready.

Idempotent on `(unit, start_date)`: a unit cannot have two tenancies beginning
the same day, so a re-run after a partial failure skips exactly what it created.

**The activation behaviour matters — read this before you run it.**
`TenancyAgreement.validate()` routes an agreement for approval when the QID or
the signed pack is missing, and pushes `Draft` to `Pending Approval`. For a
migration that is the wrong instinct: these agreements *are* live and signed,
the scans just are not in the system. Left to default, all ~250 would land as
Pending Approval — and because unit occupancy follows tenancy status, the whole
portfolio would read Vacant.

So the importer sets `status` explicitly, defaulting to Active. The controller
does not downgrade a status that is already Active; it records `missing_items`
and sets `activation_route = "Routed for Approval"`. The ledger is right from
day one and `missing_items` becomes an honest worklist of packs still to scan.
`dry_run` reports that count so it isn't a surprise.

### 3b. Opening arrears

```bash
bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.dry_run
bench --site erp.darkbrown.qa execute darkbrown.patches.seed_opening_arrears.run
```

Unmatched names go in `arrears_name_map.csv`. Aborts if the CSV total does not
match 216,519.00.

### 3c. Landlord PDC register

```bash
bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.dry_run
bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.run
```

Unmatched names go in `pdc_name_map.csv`; property codes in
`pdc_building_map.csv`. It does **not** guess buildings — `UG-169/180` covers
two and `TWAR -10 VILLAS` is a group, and that reconciliation is still open.
Unresolved codes leave `building` blank and are reported, which is a gap you can
see rather than a wrong cost centre you cannot.

---

## What changed

### Carried over from the previous zip

Unchanged from what you already reviewed: four cheque engines collapsed onto
`api.finance`; `"Bounced"` corrected to `"Returned"` in the four places that
keyed off a status the doctype cannot hold; `utils/handoffs.py` wired into
`doc_events` and the nightly after never having run; the arrears tag
prefix-collision; the PDC dedupe that was losing one real QAR 14,000 cheque;
`TEST_MODE` and the token-overlap matcher removed from both seeders;
reconciliation amount-matching; one derivation of monthly rent; `[]` vs absent
in the boot payload.

### New in this drop

**Unit occupancy no longer empties the portfolio.** `TenancyAgreement.on_update`
read only the agreement being saved:

```python
"Occupied" if self.status == "Active" else "Vacant"
```

Three faults, and all three bite during an import. `Expiring` is a live tenancy
everywhere else in the app, but fell to the else branch — so saving an agreement
inside its notice window marked an occupied unit Vacant. Saving a historical
`Expired` agreement for a unit that has a *current* tenancy did the same, so
importing any history would have emptied the portfolio one row at a time. And it
overwrote `Not Ready` and `Under Maintenance`, which are operations' to set.

A unit is now Occupied while **any** live tenancy covers it, `Reserved` is left
alone, and operations statuses are not tenancy's to touch. **This had to land
before the importer** — the two are one change.

**Financial records are no longer casually deletable.** Twelve doctypes —
Cheque, Security Deposit, Deposit Batch, Invoice Run, Utility Bill, Petty Cash
Entry, Weekly Closing, Bank Statement Import/Line, Head Lease Payment, Tenancy
Agreement, Head Lease — lose `delete` from every business role. Only System
Manager keeps it, and all twelve now have `track_changes`. None is submittable,
so `delete` was the only way they vanished, and it left nothing behind. Each has
a Terminated or Cancelled status that is the correct way to retire a record.

Making them submittable would be better still; that is a schema change with a
data migration behind it and does not belong in the same drop as an importer.

**`rent_invoicing` no longer duplicates the invoice builder.** Its own header
said only `monthly_reminder` was wired and that the builder below was "the copy
that does NOT run". That dead copy posted invoices dated today with a due date
inside the period, which core ERPNext rejects — and
`patches/run_july_billing.py` worked around it by monkey-patching
`validate_due_date` to a no-op for the duration of a migrate, then submitting a
month of invoices and swallowing every error.

`api.finance` never had the bug: it posts at `run.period_start` and derives the
due date forward. So the workaround existed entirely to prop up code nobody
called. The builder is deleted; `GENERATION_START` and `monthly_reminder` stay,
because `api.charts` and `api.md_dashboard` both import the constant from here.
`run_july_billing` now refuses.

**`patches.txt` decided, one patch at a time.** Ten registered, in dependency
order — schema first, then desk furniture, then the data-shape migration and its
fixup. Four ledger-writing importers explicitly excluded, with the reason
written down so nobody adds them later.

---

## Verification

```bash
cd verify
python3 harness.py          # 33 checks, server side
python3 importer_e2e.py     # 16 checks, importer end to end
npm install jsdom && node routes.js
```

Current results:

```
harness.py        33 passed, 0 failed   (119 whitelisted endpoints, all gated)
importer_e2e.py   16 passed, 0 failed
routes.js         25 passed, 0 failed   (1575 route renders)
compileall + json  clean across 225 files
```

The harness imports the real modules against a stubbed Frappe loaded with the
actual doctype JSON. The stub now **runs the real doctype controllers** on
`insert`/`save` — without that, `importer_e2e`'s occupancy assertions passed
while testing nothing, which is how I found the gap.

Run against the pristine tree the same harness fails 26 of 33, including
`ValidationError: Bounced is not a valid value for Cheque.status` and `core
validation still monkey-patched`. That is the point of it: it detects the bugs,
so a pass means something.

`importer_e2e.py` drives the real importer over a real CSV and then checks what
it created — including a unit whose name contains a space (`Najma Tower-501`),
a historical Expired row that must not empty its unit, a `Not Ready` unit the
importer must not overwrite, an idempotent second run, and an unmatched tenant
that must abort the whole thing.

---

## Still open

- **Submittability.** The right end state for Cheque and Security Deposit is
  submit/cancel/amend rather than edit-in-place. Schema change plus migration.
- **~250 agreements is my assumption of the volume**, not a verified count. The
  importer does not care, but `dry_run` will tell you the real number.
- **The eight cutover questions** are untouched by this — unit inventory
  (305 vs 274), UG-169/UG-180, PDC sheet treatment, the authoritative owner
  register tab, multi-unit PDC rows, terminated buildings, keymoney
  capitalisation. The importers will refuse rather than guess where these bite,
  which is the point, but they still need answering.
- **Stage 2I (Owners/Shareholders)** and Q21, the owners' current account
  posting target.

## For Anoop

- **Returned-cheque bank charges** — absorbed (as shipped: Dr charge account /
  Cr bank, cost centre the building) or recharged to the tenant?
- **Security deposits banked** — confirm the liability account is named exactly
  `Security Deposits Held` in the live CoA.
- **Rent-free treatment** — as-incurred vs straight-line, still open, still
  material. The N5 grace-period alert now actually fires, so Accounts will start
  being told seven days before each window ends.
