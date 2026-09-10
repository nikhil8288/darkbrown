"""Stage 10 — arrears.

44 collection cases, QAR 124,202 outstanding at 31 July 2026. One case per
tenant per unit rather than one per unpaid month, because a case is a
conversation with a person about a flat, not a row in a ledger — somebody four
months behind is one problem, not four.

**124,202 is a much smaller number than the 468,314 stage 6 reports
uncollected, and both are right.** The chain:

    charged                         5,306,783
    less received                  -4,838,469   = 468,314 not collected
    less advances held               -240,250   = 228,064 actually fell due
    less earlier dues since paid     -103,862   = 124,202 still outstanding

Advances are money already in hand against rent not yet due, so counting them
as arrears would show a debt that does not exist. The 103,862 is rent that was
late and has since been paid. What is left is what somebody still owes.

**No invoices, so no `invoices` child rows.** The doctype links cases to Sales
Invoices, and there are none — nothing in this rebuild has posted to the
ledger. `outstanding_amount` carries the figure directly. When Anoop sets the
opening position and invoices exist, the cases can be attached to them; they
are keyed on tenant and unit, which is what the invoices will carry.

**The source was checked two ways.** The arrears come from the Revenue tab's
Net Rent Due column, and the Pendings tab turns out to be exactly the same 56
rows — a curated copy, not an independent list. Agreeing with it proves
nothing on its own, so the reconciliation above is what the gate tests.

Every case dates from the month the rent first went unpaid, not from the
cutover, so `days_past_due` is honest about how old the debt is. The oldest
runs to October 2025.
"""

import frappe

from darkbrown.load import common as C

STAGE = "10"
SOURCE = "arrears.csv"

CUTOFF = "2026-07-31"


def _money(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _resolve(rows):
    keymap = {}
    for r in C.rows("tenants.csv"):
        n = C.norm(r.get("customer_name"))
        if n:
            keymap[n] = (r.get("match_key") or "").strip() or n
    tenants = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        n = C.norm(c.customer_name or c.name)
        tenants[keymap.get(n, n)] = c.name

    agreements = {}
    for t in frappe.get_all("Tenancy Agreement",
                            fields=["name", "tenant", "unit", "start_date",
                                    "status"]):
        agreements.setdefault((t.unit, t.tenant), []).append(t)

    existing = set()
    for c in frappe.get_all("Collection Case", fields=["unit", "tenant"]):
        existing.add((c.unit, c.tenant))

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        b = (r.get("building") or "").strip()
        unit_no = (r.get("unit_no") or "").strip()
        mk = (r.get("match_key") or "").strip()
        unit = "%s-%s" % (b, unit_no)
        amount = _money(r.get("outstanding_amount"))

        def bad(column, value, rule, message):
            problems.append(C.Problem(SOURCE, i, column, value, rule, message))

        key = (unit, mk)
        if key in seen:
            bad("match_key", mk, "duplicate_in_file",
                "same tenant and unit as row %d" % seen[key])
            continue
        seen[key] = i

        tenant = tenants.get(mk)
        if not tenant:
            bad("match_key", mk, "tenant_unresolved",
                "no Customer under this key — stage 4 must be gated first")
        if not frappe.db.exists("Unit", unit):
            bad("unit_no", unit, "unit_unresolved", "no Unit on the site")
        if not frappe.db.exists("Building", b):
            bad("building", b, "building_unresolved",
                "no Building on the site")
        if amount is None or amount <= 0:
            bad("outstanding_amount", r.get("outstanding_amount"),
                "amount_required",
                "a collection case with nothing outstanding is not a case")

        oldest = (r.get("oldest_due_date") or "").strip()
        if not oldest:
            bad("oldest_due_date", oldest, "oldest_required",
                "without it there is no way to tell how old the debt is")
        elif oldest > CUTOFF:
            bad("oldest_due_date", oldest, "oldest_after_cutover",
                "rent cannot have fallen due after the cutover")

        agreement = None
        if tenant:
            found = agreements.get((unit, tenant)) or []
            live = [a for a in found if a["status"] in ("Active", "Expiring")]
            pick = sorted(live or found, key=lambda a: str(a["start_date"]))
            if pick:
                agreement = pick[-1]["name"]
            else:
                bad("match_key", mk, "no_tenancy",
                    "the tenant has no agreement on this unit — stage 5 "
                    "should have created one")

        # `key` is (unit, match_key) — the worksheet's vocabulary. The site
        # stores the Customer docname. Comparing the two is what made stage 4
        # reload itself on every run, and stage 8 nearly do the same.
        plan.append({"row": i, "raw": r, "unit": unit, "building": b,
                     "tenant": tenant, "agreement": agreement,
                     "amount": amount or 0.0, "oldest": oldest,
                     "existing": (unit, tenant) in existing})
    return plan, problems


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    fresh = [p for p in plan if not p["existing"]]
    total = sum(p["amount"] for p in plan)
    oldest = min([p["oldest"] for p in plan if p["oldest"]] or [""])
    deep = sorted(plan, key=lambda p: -p["amount"])[:5]

    def q(v):
        return frappe.utils.fmt_money(v, currency="QAR")

    print("STAGE 10 CHECK — arrears")
    print("  %s: %d case(s), %d to create" % (SOURCE, len(rows), len(fresh)))
    print("  outstanding at %s   %s" % (CUTOFF, q(total)))
    print("  across %d building(s), oldest debt from %s"
          % (len({p["building"] for p in plan}), oldest))
    print("  the largest five:")
    for p in deep:
        print("        %-9s %-10s %12s  %s month(s), since %s"
              % (p["building"], p["raw"].get("unit_no"), q(p["amount"]),
                 p["raw"].get("months_in_arrears"), p["oldest"]))
    print("  this is net of %s held on advance and %s of earlier dues since "
          "collected — see the module notes" % (q(240250), q(103862)))
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
        frappe.throw("Stage 10 refused: %d problem(s). Run Check."
                     % len(problems))

    made, failed = 0, []
    print("STAGE 10 RUN — arrears")
    for p in plan:
        if p["existing"]:
            continue
        r = p["raw"]
        try:
            c = frappe.new_doc("Collection Case")
            c.tenant = p["tenant"]
            c.tenancy_agreement = p["agreement"]
            c.building = p["building"]
            c.unit = p["unit"]
            c.status = (r.get("status") or "Open").strip()
            c.trigger = (r.get("trigger") or "Past Due").strip()
            c.opened_on = (r.get("opened_on") or CUTOFF).strip()
            c.outstanding_amount = p["amount"]
            c.oldest_due_date = p["oldest"]
            c.days_past_due = int(r.get("days_past_due") or 0)
            c.reference = (r.get("reference") or "")[:140]
            c.manual_reason = r.get("manual_reason") or ""
            c.flags.ignore_permissions = True
            c.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            failed.append((p["unit"], (text.splitlines() or ["?"])[0][:90]))

    if failed:
        C.report([C.Problem(SOURCE, "-", "unit_no", n, "insert_failed", w)
                  for n, w in failed])
    print("  opened %d collection case(s)" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def reload():
    print("STAGE 10 RELOAD — arrears")
    return run()


def gate():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    want_total = round(sum(p["amount"] for p in plan), 2)

    site = frappe.get_all("Collection Case",
                          fields=["name", "tenant", "unit", "building",
                                  "outstanding_amount", "oldest_due_date",
                                  "tenancy_agreement"])
    on_site = len(site)
    site_total = round(sum(float(s.get("outstanding_amount") or 0)
                           for s in site), 2)
    no_agreement = len([s for s in site if not s.get("tenancy_agreement")])
    orphan = len([s for s in site
                  if not frappe.db.exists("Customer", s["tenant"])
                  or not frappe.db.exists("Unit", s["unit"])])
    future = len([s for s in site
                  if str(s.get("oldest_due_date") or "") > CUTOFF])

    # the whole point of the stage: 124,202 has to be the 468,314 stage 6
    # reports, less advances held and less earlier dues since collected
    charged = round(sum(float(h.get("rent_received") or 0)
                        for h in frappe.get_all("Historical Monthly PL",
                                                fields=["rent_received"])), 2)

    checks = [
        ("every case in the worksheet exists", on_site == len(plan),
         "%d on site vs %d expected" % (on_site, len(plan))),
        ("the outstanding reconciles", abs(site_total - want_total) < 1.0,
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(site_total, currency="QAR"),
            frappe.utils.fmt_money(want_total, currency="QAR"))),
        ("every case is tied to a tenancy", not no_agreement,
         "none loose" if not no_agreement
         else "%d without an agreement" % no_agreement),
        ("no case points at a tenant or unit that is gone", not orphan,
         "%d orphan(s)" % orphan),
        ("no debt falls due after the cutover", not future,
         "none" if not future else "%d dated after %s" % (future, CUTOFF)),
        ("stage 6 is still loaded to compare against", charged > 0,
         "%s received on the history"
         % frappe.utils.fmt_money(charged, currency="QAR")),
        ("the worksheet still resolves cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
