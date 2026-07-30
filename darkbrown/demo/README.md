# Demo data

A dummy portfolio that exercises every write path in the application, so the
workflow can be proven before real data goes anywhere near it.

The seeder does **not** write records to the database directly. Every record
is created by calling the same whitelisted function the screen calls —
`portfolio.onboard_building`, `agreements.create_agreement`,
`finance.return_cheque`, and so on. That is the whole point: if the seed runs
clean, the write path runs clean.

## Commands

    # count what is on the site now — writes nothing
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.preview

    # purge, seed, verify, in one go
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.rebuild \
          --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"

    # or one at a time
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.purge \
          --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.seed
    bench --site erp.darkbrown.qa execute darkbrown.demo.run.verify

`rebuild` is irreversible. Take a backup first:

    bench --site erp.darkbrown.qa backup --with-files

## What the purge removes

Every DarkBrown record, plus the ERPNext records this app created: Sales
Invoices, Payment Entries and Journal Entries against DarkBrown parties, the
tenant Customers, the landlord Suppliers, and the per-building Cost Centres.

It leaves the Company, the chart of accounts, bank accounts, users, roles,
DBR Settings and Document Requirements alone. Scoping is by party rather than
by doctype, so unrelated ERPNext data on the same site survives. Pass
`wide=True` to take every invoice and payment on the site regardless of party.

## What the seed lays down

Three buildings, twenty-four units, twenty tenancies, two banks, one shop.
Small enough to read end to end, large enough that every branch has something
to land on. Full detail in `dataset.py`, summary in the table below.

| | Najma Tower | Bin Mahmoud Residency | Al Sadd Court |
|---|---|---|---|
| Area | Najma, Zone 27 | Fereej Bin Mahmoud, Zone 23 | Al Sadd, Zone 38 |
| Landlord | Abdulla Nasser Al-Mannai | Al Rayyan Properties W.L.L. | Hamad Jassim Al-Kuwari |
| Units | 12 | 8 | 4 |
| Head lease | QAR 780,000/yr | QAR 456,000/yr | QAR 240,000/yr |
| Sublease | QAR 82,300/mo | QAR 37,200/mo | QAR 30,700/mo |
| Spread | +21.0% | **−2.2%** | +34.9% |

Bin Mahmoud is loss-making on purpose. One void, one agreement stuck in
approval, and the building goes underwater — which is what the loss-maker
panel on the Command Centre is for.

Portfolio totals: QAR 150,200 in against QAR 123,000 out, an 18.1% spread,
79% occupancy.

## Deliberate states

Nothing in the dataset is uniform. Each of these exists so that a screen has
a real case to render rather than an empty list.

| State | Where |
|---|---|
| Void unit | Najma 402, Bin Mahmoud 3B |
| Off-market unit | Najma 602 (under maintenance), Al Sadd 3 (not ready) |
| Agreement self-approved | 18 of 20 |
| Agreement activated on override | Fatima Zahra Bennani, Najma 502 (no QID) |
| Agreement stuck in approval | Chen Wei, Bin Mahmoud 3A (no signed pack) |
| Cash-paying tenants | 4, banked on collection slips |
| Returned cheque | Deepak Sharma — clears first, then bounces, so the reversal is tested |
| Replacement cheque | issued against that bounce |
| Two months of arrears | Elena Petrova, Najma 401 |
| Escalated collection case | the same tenant, after a broken promise |
| Over-ceiling emergency job | Najma 602 compressor, QAR 3,500 |
| Rechargeable job | Bin Mahmoud 2B, recharged onto the next invoice |
| Live move-out | Anil Joseph Thomas, Najma 501, held at settlement |
| Superseded document | Kiran Prasad's renewed QID |
| Rejected document | Chen Wei's passport scan |
| Amendment above MD threshold | Gulf Horizon rent review, QAR 15,600 impact |
| Amendment below it | Sunita Menon parking, approved by the GM |
| Invoice run awaiting the GM | Najma Tower, current month |

## Dates

Everything is anchored to the month the seeder runs in. Rebuild it in six
months and the leases, invoices and expiry queue are all still current.

Three months of rent are invoiced: the current month and the two before it.
Post-dated cheques run twelve per tenant from the agreement start, so the
cheques falling inside that window are the ones that clear.

## Verification

`run.verify` asks two questions.

First, does `api.app.seed` carry every module. A module that returns nothing
is dropped from the boot payload and the prototype silently falls back to its
own demo figures — which looks fine on screen and hides the fact that nothing
is wired. After a seed, a missing module is a failure.

Second, do the numbers hold: occupancy, arrears, collection rate, the spread,
the approvals queue, the cheque lifecycle. Twenty-odd assertions against the
records rather than the screen.

## Adding to the dataset

`dataset.py` is plain data. Add a building to `BUILDINGS`, a tenancy to
`TENANCIES`, a job to `JOBS`. Amounts are in full QAR; the seeder divides by
a thousand where the API expects thousands, so what is written here is what
should appear on a statement. `start_months` and friends are offsets from the
first of the current month.
