"""Stage 1 — the landlords.

Suppliers come before buildings because `Building.landlord` is mandatory. The
previous plan had buildings first and would have failed on the first row.

`portfolio._landlord()` creates a Supplier on the fly from whatever name it is
handed, matching on the exact string. That is fine for one building added by
hand and wrong for a bulk load: "Al Adekhar Real Estate Company WLL" and "Al
Adekhar Real Estate Co." would become two landlords owning ten villas between
them, and the payables would split down the middle of one relationship. So the
names are loaded once here, deliberately, and Stage 2 only ever looks them up.
"""

import frappe

from darkbrown.load import common as C

STAGE = "1"
SOURCE = "landlords.csv"


def _supplier_group():
    for name in ("Services", "All Supplier Groups"):
        if frappe.db.exists("Supplier Group", name):
            return name
    grp = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
    if not grp:
        frappe.throw("No Supplier Group on the site.")
    return grp


def _resolve(rows):
    """Match each worksheet name to what is already on the site, by folded name."""
    existing = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        existing[C.norm(s.supplier_name or s.name)] = s.name

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        name = (r.get("supplier_name") or "").strip()
        if not name:
            problems.append(C.Problem(SOURCE, i, "supplier_name", name,
                                      "name_required", "blank landlord name"))
            continue
        key = C.norm(name)
        if key in seen:
            problems.append(C.Problem(
                SOURCE, i, "supplier_name", name, "duplicate_in_file",
                "same landlord as row %d once case is ignored" % seen[key]))
            continue
        seen[key] = i
        plan.append({"row": i, "name": name, "key": key,
                     "ident": (r.get("ident") or "").strip(),
                     "existing": existing.get(key)})
    return plan, problems


def check():
    """Writes nothing. Reports what would be created and everything wrong."""
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    fresh = [p for p in plan if not p["existing"]]

    print("STAGE 1 CHECK — landlords")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d to create, %d already on the site"
          % (len(fresh), len(plan) - len(fresh)))
    C.report(problems)
    for p in fresh:
        print("    + %-52s %s" % (p["name"][:52], p["ident"][:40]))
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "problems": len(problems),
            "clean": not problems}


def run():
    """Create them. Idempotent — a second run creates nothing."""
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 1 refused: %d problem(s) in %s. Run Check."
                     % (len(problems), SOURCE))

    group = _supplier_group()
    made, failed = 0, []
    print("STAGE 1 RUN — landlords")
    for p in plan:
        if p["existing"]:
            continue
        try:
            doc = frappe.new_doc("Supplier")
            doc.supplier_name = p["name"]
            doc.supplier_group = group
            doc.supplier_type = "Company" if _looks_corporate(p["name"]) \
                else "Individual"
            if frappe.get_meta("Supplier").has_field("db_is_landlord"):
                doc.db_is_landlord = 1
            if p["ident"] and frappe.get_meta("Supplier").has_field("tax_id"):
                doc.tax_id = p["ident"][:140]
            doc.flags.ignore_permissions = True
            doc.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            failed.append((p["name"], str(e).splitlines()[0][:90]
                           if str(e).strip() else type(e).__name__))

    for name, why in failed:
        print("  ! %s: %s" % (name, why))
    print("  created %d landlord(s)" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def _looks_corporate(name):
    low = name.lower()
    return any(w in low for w in (" w.l.l", " wll", " llc", " company", " co.",
                                  " est.", " group", " trading", " real estate"))


def gate():
    """Audited against the worksheet, not against what run() claimed."""
    rows = C.rows(SOURCE)
    wanted = {C.norm(r["supplier_name"]) for r in rows if r.get("supplier_name")}

    on_site = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        on_site.setdefault(C.norm(s.supplier_name or s.name), []).append(s.name)

    missing = sorted(w for w in wanted if w not in on_site)
    doubled = sorted(k for k, v in on_site.items() if k in wanted and len(v) > 1)

    flagged = 0
    if frappe.get_meta("Supplier").has_field("db_is_landlord"):
        flagged = len(frappe.get_all("Supplier", filters={"db_is_landlord": 1}))

    checks = [
        ("every landlord in the worksheet exists", not missing,
         "%d of %d found%s" % (len(wanted) - len(missing), len(wanted),
                               "" if not missing else "; missing: %s"
                               % ", ".join(missing[:3]))),
        ("none created twice", not doubled,
         "no duplicates" if not doubled else "duplicated: %s"
         % ", ".join(doubled[:3])),
        ("flagged as landlords", flagged >= len(wanted),
         "%d flagged db_is_landlord" % flagged),
    ]
    return C.gate_result(STAGE, checks)
