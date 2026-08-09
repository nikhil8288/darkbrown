# V1 doctype names removed

Repo-root overlay. **Supersedes `darkbrown_role_guards.zip`.** Apply this one;
it contains that batch as well.

**Needs a migrate** — one new field on DBR Settings.

    git pull
    bench --site <site> migrate
    bench --site <site> clear-cache
    bench --site <site> restart

---

# 1 — There were three V1 names, not one

The running notes had this as eleven dead notification rules. The sweep found
three doctype names V2 never defines, in 24 files:

| V1 name | V2 name | refs | files |
|---|---|---|---|
| `Tenant Rental Agreement` | `Tenancy Agreement` | 41 | 12 |
| `PDC Cheque` | `Cheque` | 60 | 11 |
| `Landlord Contract` | `Head Lease` | 27 | 7 |

You confirmed PDC cheques work in V2, and the code agrees: `Cheque` carries the
whole lifecycle — direction, party, cheque_date, Received → Deposited →
Presented → Cleared → Returned → Replaced, `payment_entry`, `replaced_by`. So
`PDC Cheque` was pure V1 leftover, not a parallel doctype. Nothing was migrated;
the names were simply wrong.

## The fields had to move too

Renaming a doctype and leaving V1 field names just moves the failure. Checked
by AST at every call site:

- `Tenant Rental Agreement` → `Tenancy Agreement`: **all 9 fields survive.** Pure rename.
- `PDC Cheque` → `Cheque`: **all 5 fields survive.** Pure rename.
- `Landlord Contract` → `Head Lease`: four had to be mapped —

      contract_start_date  ->  start_date
      contract_end_date    ->  end_date
      grace_period_days    ->  rent_free_days
      total_owner_rent     ->  monthly_rent

`total_owner_rent` is added once per month as an outflow in the projection, so
it is the monthly figure, not the annual one. `grace_period_days` is used as
"grace end = start + N days", which is exactly `rent_free_days`.

Then the same sweep run against every doctype found more V1 field names on
doctypes that **do** exist:

| Doctype | V1 field | V2 field |
|---|---|---|
| Unit | `occupancy_status` | `status` |
| Unit | `unit_name` | `unit_no` |
| Unit | `furnishing_status` | `furnishing` |
| Unit | `monthly_rent` | `asking_rent` |
| Document Register | `party_name`, `id_number` | `party`, `document_no` |
| Document Register | `notes` | `rejection_reason` |
| Party Document | `id_number`, `holder_name` | `document_no`, parent party |

`Unit.monthly_rent` needed care: `monthly_rent` is correct on Tenancy Agreement
and Head Lease and wrong only on Unit, so this was edited by hand at each site
rather than swept.

# 2 — What this was actually breaking

**Occupancy and vacancy read zero.** `number_cards.vacant_units` and
`occupancy_pct` both counted `Unit.occupancy_status`, which does not exist. Two
of the ten number cards, wrong on every workspace.

**The Documentation role could not open `/doc-intake`.** `www/doc_intake.py`
gates on `Legal and Documentation` — a role `install.py` never creates. Same
orphan role sat on `Document Archive`'s permission table and in four patches.
All now read `Documentation`.

**Cheque clearing wrote unattributed entries.** `pdc_accounting` looked up
building and tenant off `Tenant Rental Agreement`, got `None`, and posted
anyway — no cost centre, no party.

**The 12-month projection was wrong in four separate ways**, which is worth
stating plainly because D80 went into it:

1. `charts.py` raised `ImportError` on load, so it never ran at all (fixed in
   the previous batch).
2. Head-lease outflow read `Landlord Contract` → **zero outflow every month**.
3. PDC inflow read `PDC Cheque` → **zero**, and silently, because the code
   checks whether the doctype exists and returns `[]` when it does not.
4. The danger-month test compared the cumulative line against
   `DBR Settings.minimum_cash_floor`, **which was not a field** —
   `set_cash_floor` wrote to nothing and the floor was always zero.

The projection would have reported rent coming in against no cost at all. Its
one job is finding the month cash goes under.

# 3 — Where a rename was not enough

**`utils/pdc_accounting.py` — the security-cheque test.** V1 asked a
`cheque_type` field on the cheque. V2 has no such field and does not need one:
a security cheque is the one a `Security Deposit` record points at through
`receipt_cheque`. Ported to `is_security_cheque()`, reading it from there. The
safety property is unchanged — a security cheque must never create income.

This module could not simply be deleted, though it looked dead:
`doc_intake.apply_statement_line` imports and calls `mark_cleared`. It is
reachable through `/doc-intake`.

**It is also a second engine.** `mark_cleared` / `mark_bounced` duplicate
`finance.clear_cheque` / `finance.return_cheque`, and both are live — one from
the shell, one from doc-intake. Two engines posting the same Payment Entry is
how a fix lands in the wrong one. A warning header now says so. **Fold one into
the other before either is trusted with real clearings.** Not done here; it
needs a real database to test.

**`patches/seed_pdc_outgoing.py`** wrote `direction: "Outgoing (to Landlord)"`,
`cheque_number` and `status: "Pending"` — none of which V2 accepts. Now
`Outgoing`, `cheque_no`, `Received`, plus `party_type: Supplier`. Still a
one-shot loader with a `dry_run`; run that first.

**`patches/extend_pdc_cheque.py` deleted.** It added custom fields and desk-form
buttons to a doctype that does not exist. V2's Cheque carries `cleared_on` and
`returned_on` natively and no business user sees the desk.

# 4 — New field

`DBR Settings.minimum_cash_floor` (Currency, QAR) — the absolute floor the
projection tests against. Distinct from `reserve_months` above it, which is a
multiple of monthly cost rather than an amount. **Set it after migrating**, or
the danger month is still measured against zero.

# 5 — Tested, and not

- Every reference to the three V1 names is gone. One deliberate exception:
  `attention.py:14`, a docstring explaining the old bug in the past tense.
- **Zero unresolvable field references app-wide** — AST check across every
  `get_all` / `get_value` / `exists` / `count` call against every DocType JSON.
  Before this batch: 20.
- All 106 endpoints still import; guard sweep still clean, nothing reachable by
  a user holding no DarkBrown role.
- Whole app byte-compiles, all JSON parses.
- Overlay applied to a fresh clone of HEAD and re-verified end to end.

**Not verified:** anything against a real database. In particular, if any live
site rows were created carrying V1 field values, this changes what the code
reads, not what is stored. Worth spot-checking occupancy on the workspace after
migrate — it should stop reading zero.

**Still open from the audit:** the handover flow (nothing moves units out of
"Not Ready"), `patches.txt` running one patch of thirteen, and rent-free
treatment with Fatima. Next in order.
