# AK-12 — clean rebuild

Wipe the site, load one building, its eight units, its tenants, their agreements
and nine months of real payment history. Nothing else.

---

## Part 1 — what I found reading the whole chain

### The purge cannot reach your leftover Customers

`demo/purge.py` scopes the parties it deletes by flag:

```python
def _tenants():   return frappe.get_all("Customer", {"db_is_tenant": 1})
def _landlords(): return frappe.get_all("Supplier", {"db_is_landlord": 1})
```

Your diagnostic showed **272 Customers, 2 flagged**. A plain purge would delete
those 2 and walk past the other 270. `wide=True` does not help — it widens the
ledger sweep only; Customer and Supplier are always scoped by flag.

That is why the site never came back clean. `full_reset.py` flags the orphans
first so the existing purge can see them, then calls the real purge. It does not
reimplement deletion.

### Arrears were being asserted, not derived

`seed_opening_arrears` posted a 600 figure because no transaction history was
being loaded. With history loaded the 600 falls out on its own — G-01B is
charged 3,200 and pays 3,000 three times. Running both would double it. The
arrears file ships empty and `EXPECTED_TOTAL` is 0.00.

### The workbook's "net rent due" is not rent minus received

Rent 256,400, Received 241,500, Advance 14,000. That leaves 900, but the
workbook says 600. The gap is the `Previous Due Rcvd` column: negative when an
earlier shortfall was later recovered. Cash actually collected is

```
collected = Received + Advance − Previous Due Rcvd
```

which gives 255,800 and an outstanding of exactly 600, matching the
Reconciliation sheet per unit. Had I used the obvious subtraction the ledger
would have carried a phantom 100 against F-01 and 800 against G-01B.

### Tenant history is per row, not per unit

G-01A changed hands: Muhammed Ashique Paracholakuzhi to Dec-2025 at 3,400, empty
January and February, Mohammed Saeed Abdul Azeez from Mar-2026 at 3,000. My
first cut keyed history by unit, which credited 6,800 of the previous tenant's
payments to the current one. Fixed — each row's own tenant owns its invoice and
receipt. Both are Customers; only the current one holds a tenancy.

P-02's Imed Barouni is the same case: eight months of payments, vacated Jul-2026,
so he is a Customer with history and no agreement. That is why `customers.json`
holds nine names for seven tenancies.

### Two placeholders in the live shell, not data faults

`shell/index.html` line 4079 hardcodes the **Unit history** panel — "Move-in
inspection completed", "Agreement signed", "AC service", "Rent revised at
renewal" — as fixed offsets from today. That is why an empty unit showed an
agreement signed in Aug-25.

`api/app.py` `units()` computes the **Landlord cost** column as
`rent * 0.78`. It is not read from the head lease, so the Spread column is
arithmetic on a guess. Neither blocks this load; both should go before anyone
reads a dashboard as fact.

---

## Part 2 — the load

| File | What it is |
|---|---|
| `full_reset.py` | **new** — flags orphan parties, then purges |
| `buildings_payload.json` | 1 building, 8 units, 1 head lease |
| `customers.json` | 9 tenants (7 current, 2 former) |
| `tenancies.csv` | 7 agreements |
| `ak12_history.csv` | **new** — 69 rows, Nov-2025 → Jul-2026 |
| `load_ak12_history.py` | **new** — posts invoices and receipts |
| `load_customers.py` | fixed: leaf group, flags existing parties |
| `import_tenancies.py` | fixed: reads CSVs as `utf-8-sig` |
| `seed_opening_arrears.py` | fixed: same, and `EXPECTED_TOTAL = 0.00` |
| `opening_arrears.csv` | header only |
| `cutover.py` | Payment history added as step 5 |

### Order

Customers → Buildings and units → Tenancies → Arrears (no-op) → Payment history.
History last because it posts against the Customers and needs them to exist.

### Run it

```
bench --site erp.darkbrown.qa execute darkbrown.patches.full_reset.preview
```

Read what it says. Then:

```
bench --site erp.darkbrown.qa execute darkbrown.patches.full_reset.run \
    --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
```

It prints what is left. Every line should read 0. Then `#/data` → **Dry run** →
**Load for real**.

### What you should see

```
Customers          9      created, all flagged as tenants
Buildings          1      AK-12
Units              8      7 Occupied, P-02 Void
Tenancy Agreement  7
Sales Invoice     69      opening invoices, Nov-2025 to Jul-2026
Payment Entry     69
charged      256,400.00
collected    255,800.00
outstanding      600.00   all of it G-01B
```

Verified before packaging by running the actual shipped modules against a stub
with a working ledger: 69 invoices, 69 receipts, outstanding 600.00 against
Amani Guesmi and zero against everyone else, no unallocated cash. Re-running the
whole sequence created nothing and left the totals unchanged.

### One accounting decision, for Anoop

The 69 invoices post `is_opening = "Yes"`, so the debit lands in Temporary
Opening rather than a revenue account. The receivable and the receipt are real;
the income is not recognised twice, because these nine months already sit in the
manual books.

The consequence: **AK-12 shows no revenue in the ERP P&L before Jul-2026.** That
history lives in Historical Monthly PL, which this load does not touch. If Anoop
wants the ledger to carry the income too, the invoices need a real income
account and the Historical Monthly PL rows for AIN KHALID-12 must be dropped, or
the same rent is counted twice. One or the other, not both.

---

## Still open on AK-12

- **F-01 and G-01B renewals.** Both expired (31-May-2026, 30-Jun-2026) with rent
  collected through July. Both references end `RN01`, so an `RN02` exists on
  paper. The expiry job will flip both to Expired and void the units until those
  are loaded.
- **Four units have no contract terms** — F-02, G-01, O-01, P-01. Rents verified
  against nine months of receipts; dates are placeholders.
- **Building** still missing municipality, floors, parking, lift.
- **Water account 938533** has nowhere to go. `Building` has no water field.
- **G-01A rent fell 3,400 → 3,000** on the tenant change. Confirm it was agreed.
