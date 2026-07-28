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

## Roles

`Managing Director`, `General Manager`, `Accounts`, `Documentation`,
`Maintenance`. Assign at least one to every user — a user with none is refused
at `/darkbrown` by the renderer.

## Wired to live data

- **Portfolio** — buildings, units, onboarding wizard, unit status (read + write)
- **Operations** — collection cases, maintenance jobs, move-out lifecycle (read + write)

Everything else still renders its demonstration values. A module with no data
is left out of the boot payload entirely, so those screens show sample figures
rather than zeros. Wire further modules by replacing one seeded array at a
time.
