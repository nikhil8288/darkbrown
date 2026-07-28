#!/usr/bin/env bash
# Run from the bench directory:  bash check_darkbrown.sh <site>
SITE="${1:?usage: check_darkbrown.sh <site>}"
echo "== layout =="
[ -f apps/darkbrown/pyproject.toml ] && echo "  ok  pyproject at app root" || echo "  FAIL pyproject missing at apps/darkbrown/"
[ -f apps/darkbrown/darkbrown/hooks.py ] && echo "  ok  hooks in package" || echo "  FAIL hooks.py missing"
echo "== registration =="
grep -q '^darkbrown$' sites/apps.txt && echo "  ok  in sites/apps.txt" || echo "  FAIL not in sites/apps.txt — run: bench setup requirements --app darkbrown"
echo "== import =="
bench --site "$SITE" console <<'PY'
import frappe
print("  frappe", frappe.__version__)
try:
    import erpnext; print("  erpnext", erpnext.__version__)
except Exception as e: print("  erpnext MISSING", e)
import darkbrown; print("  darkbrown", darkbrown.__version__)
want = ["Building","Unit","Head Lease","Tenancy Agreement","Agreement Amendment",
        "Cheque","Cheque Book","Deposit Batch","Invoice Run","Security Deposit",
        "Collection Case","Move Out Case","Maintenance Request",
        "Document Register","Document Requirement","Utility Meter","Utility Bill",
        "DBR Settings"]
missing = [d for d in want if not frappe.db.exists("DocType", d)]
print("  doctypes present:", len(want)-len(missing), "of", len(want))
print("  missing:", missing or "none")
print("  workspaces:", frappe.get_all("Workspace", filters={"module":"Darkbrown"}, pluck="name"))
print("  pages:", frappe.get_all("Page", filters={"module":"Darkbrown"}, pluck="name"))
PY
