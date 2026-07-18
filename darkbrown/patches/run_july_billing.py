"""TEST-PHASE patch: generate July 2026 invoices, submit them, and open
Collection Cases — all automatically during migrate. No terminal needed.

Runs after the two seed patches (order in patches.txt). Defensive: any
failure is printed but never breaks the migrate.

Remove from patches.txt (or leave — patches only run once) before the
real go-live.
"""
import traceback

import frappe


def _try(label, fn, *a, **k):
    try:
        out = fn(*a, **k)
        print("OK  %s" % label)
        return out
    except Exception:
        print("FAIL %s (non-fatal):" % label)
        traceback.print_exc()


def _generate_invoices():
    from darkbrown.utils.rent_invoicing import generate_monthly_invoices
    generate_monthly_invoices("2026-07-01")


def _submit_drafts():
    # TEST PHASE ONLY: bulk-submit whatever the invoicer drafted.
    for dt in ("Sales Invoice", "Purchase Invoice"):
        if not frappe.db.exists("DocType", dt):
            continue
        names = frappe.get_all(dt, filters={"docstatus": 0}, pluck="name")
        n = 0
        for name in names:
            try:
                doc = frappe.get_doc(dt, name)
                doc.flags.ignore_permissions = True
                doc.submit()
                n += 1
            except Exception as e:
                print("  could not submit %s %s: %s" % (dt, name, e))
        print("  submitted %d of %d draft %ss" % (n, len(names), dt))


def _open_cases():
    from darkbrown.utils.collections import auto_open_cases
    auto_open_cases()


def execute():
    _try("generate July 2026 invoices", _generate_invoices)
    _try("submit draft invoices", _submit_drafts)
    _try("auto-open collection cases", _open_cases)
    frappe.db.commit()
    print("run_july_billing patch done")
