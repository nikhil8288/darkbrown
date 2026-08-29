# Loading the data without a terminal

Everything below happens in GitHub Desktop and then in the app itself. There is
no command line in this at all.

## Part 1 — get the files onto the server

1. Unzip this over your local `darkbrown` folder, replacing when asked.
2. Open **GitHub Desktop**. The Changes list should show about **twelve** files.
   Six of them are new: `cutover.py`, `load_buildings.py`, `load_customers.py`,
   `tenancies.csv`, `buildings_payload.json`, `customers.json`.
3. **Check that every one has a tick beside it.** A commit only includes what is
   ticked, and new files are the ones most easily left behind. If the list shows
   two or three files rather than twelve, the unzip went to the wrong folder.
4. Write a summary — "cutover load" will do — and press **Commit to main**.
5. Press **Push origin**.
6. In Frappe Cloud, wait for the deploy to finish and the site to go green.

## Part 2 — run it from the app

Sign in as the **Managing Director** and open **Data & demo** in the sidebar.
There is a new card there called **Cutover load** with three buttons.

**Check** — writes nothing. It reports whether the files arrived, whether the
schema is migrated, whether the company and customer groups the loaders need
actually exist, and then it tries to onboard one real building and rolls it
back. If something is wrong this is what says so, in words.

Press it, wait for the log to stop, then press **Copy log** and paste it into
our chat. That single output tells me more than everything I have been able to
infer from outside the site.

**Dry run** — rehearses all four steps and writes nothing. It reports what it
*would* create. Two things in its output are normal and not errors:

- Every arrears row comes back "unmatched". Dry runs create no Customers, so
  there is nothing yet for the arrears to match against. On the real run the
  tenants exist by the time step four runs and they all match.
- Every tenancy shows no QID. Nothing has been scanned yet.

**Load for real** — writes. It runs the four steps in order and **stops at the
first one that fails**, because each depends on the one before and carrying on
would bury the real error under a second one. Each loader skips records that
already exist, so if it stops halfway you can fix the cause and press it again.

## Order

Purge the test data **before** loading, not after — the purge removes tenants
along with everything else, so loading first would delete the work. Take a
backup in Frappe Cloud first; that is the only undo.

    Count it  ->  Purge only  ->  Check  ->  Dry run  ->  Load for real

Never press **Seed** or **Rebuild** after purging. Those lay the demo portfolio
back down.

## What you should see when it finishes

    Customer             432
    Building              23
    Unit                 305
    Head Lease            23
    Tenancy Agreement    266

Opening arrears 124,202.00 across 56 rows. Monthly rent roll 725,650 and
head-lease rent 529,000 — both figures you already know, which is the point of
checking them. Then open **Balance Sheet** and **Cash Flow**: the balance sheet
should say Balanced and the cash flow Reconciled.

Every tenancy will show missing items and sit as Routed for Approval, because no
QID or signed pack is in the system yet. That is the worklist for the document
drive, not a fault.

## Two bugs fixed in this drop

`buildings_payload.json` passed the landlord as `supplier_name` where
`portfolio._landlord()` reads `name`, so every building threw "The building
needs a landlord" and nothing was created. With no units, the tenancy import had
nothing to resolve against either — which is why nothing loaded.

`load_buildings.dry_run()` then read the same wrong key and raised a KeyError, so
the documented "dry run first" step failed even after the payload was fixed.

Both are now executed end to end against the real modules rather than inspected:
432 customers, 23 buildings, 305 units, 23 head leases, 266 tenancies and the
arrears journal, in order, on a clean checkout.
