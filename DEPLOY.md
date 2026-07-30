# DarkBrown V2 — deployment

V2 is a standalone application. It carries no V1 code, no V1 data and no V1
schema. The prototype at `darkbrown/shell/index.html` **is** the application;
Frappe's desk stays at `/app` for Administrator only.

Built and validated against Frappe/ERPNext **version-15**.

---

## What serves what

| Path | Serves |
|---|---|
| `/` | login page (`templates/pages/login.html`, branded) |
| `/darkbrown` or `/db` | the application — all five business roles land here |
| `/app` | Frappe desk — Administrator only |

`renderer.py` hands the shell HTML over untouched and injects a boot payload
at the `<!--DB_BOOT-->` marker. It is deliberately **not** a Jinja template:
the CSS contains `{#kpis`, which Jinja reads as a comment opener.

---

## Fresh install on erp.darkbrown.qa

This destroys the existing site and everything in it. Take a backup off the
server first even though V1 data is being abandoned — it costs nothing and it
is the only way back.

```bash
cd ~/frappe-bench

# 1. backup, then COPY the files off the server
bench --site erp.darkbrown.qa backup --with-files
ls sites/erp.darkbrown.qa/private/backups/

# 2. drop the site and the old app folder
bench drop-site erp.darkbrown.qa --force
rm -rf apps/darkbrown
sed -i '/^darkbrown$/d' sites/apps.txt

# 3. pull V2 from GitHub
bench get-app https://github.com/nikhil8288/darkbrown --branch main

# 4. recreate the site
bench new-site erp.darkbrown.qa
bench --site erp.darkbrown.qa install-app erpnext
bench --site erp.darkbrown.qa install-app darkbrown

# 5. build and restart
bench --site erp.darkbrown.qa migrate
bench build --app darkbrown
bench restart
```

`after_install` creates the five roles, the Supplier/Customer custom fields
and the settings singleton. It is idempotent — re-running creates nothing
twice.

## Subsequent updates

```bash
cd ~/frappe-bench/apps/darkbrown && git pull
cd ~/frappe-bench
bench --site erp.darkbrown.qa migrate
bench build --app darkbrown && bench restart
```

Never extract an archive over `apps/darkbrown/`. `tar` and unzip overwrite
matching files and leave everything else behind, which produces a folder that
is two versions mixed together. Use `git pull`.

---

## Demo data and reset

`darkbrown/demo` purges the site's DarkBrown data and lays down a dummy
portfolio in its place — three buildings, twenty-four units, twenty tenancies,
with a bounce, an arrears case, a move-out and an approvals queue already in
flight. Every record is created through the app's own whitelisted APIs, so the
seed doubles as an end-to-end test of the write path.

```bash
bench --site erp.darkbrown.qa backup --with-files
bench --site erp.darkbrown.qa execute darkbrown.demo.run.preview
bench --site erp.darkbrown.qa execute darkbrown.demo.run.rebuild \
      --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
```

The purge is scoped by party, not by doctype: the Company, chart of accounts,
bank accounts, users, roles and settings survive it. It is still irreversible.

## Roles

`Managing Director`, `General Manager`, `Accounts`, `Documentation`,
`Maintenance`. Assign at least one to every user — a user with none is refused
at `/darkbrown` by the renderer.

## Wired to live data

- **Portfolio** — buildings, units, onboarding wizard, unit status
- **Operations** — collection cases, maintenance jobs, move-out lifecycle
- **Parties** — tenants as ERPNext Customers, arrears rolled up from invoices
- **Agreements** — tenancies, self-approving activation, amendments, renewals
- **Finance** — invoice runs, Sales Invoices, cheque lifecycle, receipts with
  oldest-first allocation, deposit batches, head-lease payments
- **Documents** — register, review, supersession, expiry queue
- **Approvals** — one queue over amendments, over-ceiling maintenance, deposit
  releases and invoice runs

Still on demonstration data, by decision: **Command Centre**, **Planning**,
**Owners and Shareholders**. A module with no data is left out of the boot
payload entirely, so those screens show sample figures rather than zeros.

## Ledger

ERPNext owns the books. Nothing in this app writes a GL entry directly — it
creates Sales Invoices and Payment Entries and lets ERPNext post them. A
returned cheque cancels its Payment Entry and opens a collection case rather
than only changing a status.
