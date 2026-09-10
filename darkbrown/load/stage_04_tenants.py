"""Stage 4 — the tenants.

547 distinct names appear across the two worksheets. The previous load created
547 Customers from them. This stage creates 382, and the difference is the
whole point of the stage.

Three things collapse the list, in order:

**VACANT and EMPTY are not people.** 125 revenue rows carry one or the other in
the tenant column, meaning the flat stood empty that month. Loaded literally
they become two customers who between them rented 125 flat-months.

**A short name and a full name on the same unit are one person.** `ali` and
`ali saqlain haji ahmed` both appear against MQ-56 F-02; `karen ibarrola` and
`karen ibarrola liamzon` against MR-130 F-06. 158 pairs fold this way. The
same-unit evidence is what makes it safe — two people who merely share a first
name never meet on one flat.

**Shamnadh Ponnakkatt Bavakutty is one tenant, not ten.** He was an agent, and
the OG-48 flats are still held in his name; the occupants appear inside
compound names like `shamnadh ponnakkatt bavakutty-halima akter momtajuddin`.
Those are his tenancies. The occupants' own names will be collected later.

Everything folded is recorded in `name_variants` on the row, so any merge can
be seen and undone rather than being taken on trust.
"""

import frappe

from darkbrown.load import common as C

STAGE = "4"
SOURCE = "tenants.csv"

CATEGORIES = ("", "Individual", "Company", "Staff Accommodation")


def _defaults():
    group = None
    for name in ("Individual", "All Customer Groups"):
        if frappe.db.exists("Customer Group", name):
            group = name
            break
    if not group:
        group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    territory = None
    for name in ("Qatar", "All Territories"):
        if frappe.db.exists("Territory", name):
            territory = name
            break
    if not territory:
        territory = frappe.db.get_value("Territory", {}, "name")
    if not group or not territory:
        frappe.throw("No Customer Group or Territory on the site — a Customer "
                     "cannot be created without both.")
    return group, territory


def _resolve(rows):
    existing = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        existing.setdefault(C.norm(c.customer_name or c.name), []).append(c.name)

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        name = (r.get("customer_name") or "").strip()
        key = (r.get("match_key") or "").strip() or C.norm(name)
        if not name:
            problems.append(C.Problem(SOURCE, i, "customer_name", name,
                                      "name_required", "blank tenant name"))
            continue
        if key in seen:
            problems.append(C.Problem(
                SOURCE, i, "match_key", key, "duplicate_in_file",
                "same tenant as row %d once folded" % seen[key]))
            continue
        seen[key] = i

        cat = (r.get("tenant_category") or "").strip()
        if cat not in CATEGORIES:
            problems.append(C.Problem(SOURCE, i, "tenant_category", cat,
                                      "category_unknown",
                                      "not one of the doctype's options"))
        plan.append({"row": i, "name": name, "key": key, "raw": r,
                     "existing": (existing.get(key) or [None])[0]})
    return plan, problems


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    fresh = [p for p in plan if not p["existing"]]
    folded = [p for p in plan if p["raw"].get("name_variants")]
    papers = len([p for p in plan if p["raw"].get("has_agreement") == "1"])

    print("STAGE 4 CHECK — tenants")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d to create, %d already on the site"
          % (len(fresh), len(plan) - len(fresh)))
    print("  %d have an agreement on file, %d do not"
          % (papers, len(plan) - papers))
    print("  %d name(s) were folded from more than one spelling" % len(folded))
    for p in folded[:6]:
        print("      %-30s <- %s"
              % (p["name"][:30], p["raw"]["name_variants"][:64]))
    if len(folded) > 6:
        print("      ... and %d more, all recorded in the file" % (len(folded) - 6))
    C.report(problems)
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "problems": len(problems),
            "clean": not problems}


def run():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 4 refused: %d problem(s). Run Check."
                     % len(problems))

    group, territory = _defaults()
    meta = frappe.get_meta("Customer")
    made, failed = 0, []
    print("STAGE 4 RUN — tenants")

    for p in plan:
        if p["existing"]:
            continue
        r = p["raw"]
        try:
            c = frappe.new_doc("Customer")
            c.customer_name = p["name"]
            c.customer_group = group
            c.territory = territory
            c.customer_type = ("Company"
                               if r.get("tenant_category") == "Company"
                               else "Individual")
            if meta.has_field("db_is_tenant"):
                c.db_is_tenant = 1
            for field, key in (("db_tenant_category", "tenant_category"),
                               ("db_qid", "qid"),
                               ("db_mobile", "mobile")):
                if r.get(key) and meta.has_field(field):
                    setattr(c, field, str(r[key])[:140])
            # db_nationality links to Country, so only set it when the Country
            # actually exists — "Indian" is a nationality, "India" is a Country,
            # and the worksheet mixes the two.
            nat = (r.get("nationality") or "").strip()
            if nat and meta.has_field("db_nationality") \
                    and frappe.db.exists("Country", nat):
                c.db_nationality = nat
            if r.get("email"):
                c.email_id = str(r["email"])[:140]
            c.flags.ignore_permissions = True
            c.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            lines = text.splitlines()
            failed.append((p["name"], (lines[0] if lines else "?")[:90]))

    if failed:
        C.report([C.Problem(SOURCE, "-", "customer_name", n, "insert_failed", w)
                  for n, w in failed])
    print("  created %d tenant(s)" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def reload():
    """Re-read the worksheet, adding what is missing.

    A Customer is never deleted here. Tenancies point at it, and once invoices
    exist the customer carries the receivable — removing it would orphan the
    money. Folding two names into one after the fact is a merge, not a reload,
    and has to be done deliberately.
    """
    live = frappe.db.count("Sales Invoice")
    if live:
        frappe.throw("%d invoice(s) are posted against these tenants. Merge "
                     "duplicates by hand rather than reloading." % live)
    print("STAGE 4 RELOAD — tenants")
    return run()


def gate():
    rows = C.rows(SOURCE)
    want = {(r.get("match_key") or C.norm(r["customer_name"])): r["customer_name"]
            for r in rows if r.get("customer_name")}

    on_site = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        on_site.setdefault(C.norm(c.customer_name or c.name), []).append(c.name)

    missing = sorted(k for k in want if k not in on_site)
    doubled = sorted(k for k in want if len(on_site.get(k, [])) > 1)

    flagged = 0
    if frappe.get_meta("Customer").has_field("db_is_tenant"):
        flagged = frappe.db.count("Customer", {"db_is_tenant": 1})

    # the whole reason this stage exists: 547 names became 382 people
    ghosts = [k for k in on_site
              if k in ("vacant", "empty", "n a", "not let", "unoccupied")]

    checks = [
        ("every tenant in the worksheet exists", not missing,
         "%d of %d" % (len(want) - len(missing), len(want)) +
         ("" if not missing else "; missing %s"
          % ", ".join(want[m][:22] for m in missing[:3]))),
        ("none created twice", not doubled,
         "no duplicates" if not doubled
         else "duplicated: %s" % ", ".join(doubled[:3])),
        ("flagged as tenants", flagged >= len(want),
         "%d flagged db_is_tenant" % flagged),
        ("no customer called VACANT or EMPTY", not ghosts,
         "none" if not ghosts else "found %s" % ", ".join(ghosts)),
        ("customer count matches the folded list",
         frappe.db.count("Customer", {"db_is_tenant": 1}) == len(want),
         "%d on site vs %d expected"
         % (frappe.db.count("Customer", {"db_is_tenant": 1}), len(want))),
    ]
    return C.gate_result(STAGE, checks)
