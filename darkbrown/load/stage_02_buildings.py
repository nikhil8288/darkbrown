"""Stage 2 — buildings and their head leases, together.

They load as one stage because a building without its lease is half a record.
The previous attempt created 22 buildings and no Head Lease at all, and every
building then displayed a head-lease end date of 31 Jul 2027 that somebody had
typed once as a placeholder. That date drove the 90-day renewal alert and the
expiry filter on the buildings screen. Nobody noticed because a building looks
complete without a lease behind it.

Not using `portfolio.onboard_building`: it creates a Head Lease only when both
annual_rent and start_date are truthy, and says nothing when it skips. That is
exactly the silent path that produced the placeholder dates.
"""

import frappe

from darkbrown.load import common as C

STAGE = "2"
SOURCE = "buildings.csv"

# read from the doctype rather than typed from memory: the Select option is
# "Annual", and "Annually" would have been rejected by validation
FREQ = ("Monthly", "Quarterly", "Half Yearly", "Annual")


def _resolve(rows):
    landlords = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        landlords[C.norm(s.supplier_name or s.name)] = s.name

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        code = (r.get("building_code") or "").strip()
        if not code:
            problems.append(C.Problem(SOURCE, i, "building_code", code,
                                      "code_required", "blank building code"))
            continue
        if code in seen:
            problems.append(C.Problem(
                SOURCE, i, "building_code", code, "duplicate_in_file",
                "already used on row %d" % seen[code]))
            continue
        seen[code] = i

        ll_key = C.norm(r.get("landlord"))
        ll = landlords.get(ll_key)
        if not ll:
            problems.append(C.Problem(
                SOURCE, i, "landlord", r.get("landlord"), "landlord_missing",
                "no Supplier with that name — has Stage 1 run?"))

        start, end = r.get("hl_start"), r.get("hl_end")
        if not start or not end:
            problems.append(C.Problem(
                SOURCE, i, "hl_start" if not start else "hl_end", start or end,
                "lease_dates_required",
                "a building without lease dates is half a record"))
        elif end <= start:
            problems.append(C.Problem(
                SOURCE, i, "hl_end", end, "lease_end_before_start",
                "end %s is not after start %s" % (end, start)))

        try:
            annual = int(float(r.get("annual_rent") or 0))
        except ValueError:
            annual = 0
            problems.append(C.Problem(SOURCE, i, "annual_rent",
                                      r.get("annual_rent"), "annual_rent_number",
                                      "not a number"))
        if annual <= 0:
            problems.append(C.Problem(
                SOURCE, i, "annual_rent", r.get("annual_rent"),
                "annual_rent_required",
                "no rent means no cost side, so no spread for this building"))

        freq = (r.get("payment_frequency") or "").strip()
        if freq not in FREQ:
            problems.append(C.Problem(
                SOURCE, i, "payment_frequency", freq, "frequency_unknown",
                "must be one of %s" % ", ".join(FREQ)))

        plan.append({"row": i, "code": code, "landlord": ll, "annual": annual,
                     "freq": freq, "start": start, "end": end, "raw": r,
                     "exists": frappe.db.exists("Building", code)})
    return plan, problems


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    fresh = [p for p in plan if not p["exists"]]
    total = sum(p["annual"] for p in plan)

    print("STAGE 2 CHECK — buildings and head leases")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d building(s) to create, %d already present"
          % (len(fresh), len(plan) - len(fresh)))
    print("  annual head-lease rent across the portfolio: QAR %s" % f"{total:,}")
    C.report(problems)
    free = [p for p in plan if int(p["raw"].get("rent_free_days") or 0)]
    if free:
        print("  %d building(s) carry a rent-free period:" % len(free))
        for p in free:
            print("      %-9s %s days" % (p["code"], p["raw"]["rent_free_days"]))
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "annual_rent": total,
            "problems": len(problems), "clean": not problems}


def run():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 2 refused: %d problem(s). Run Check."
                     % len(problems))

    company = C.company()
    made_b, made_h, failed = 0, 0, []
    print("STAGE 2 RUN — buildings and head leases")

    for p in plan:
        r = p["raw"]
        try:
            if not p["exists"]:
                b = frappe.new_doc("Building")
                b.building_name = p["code"]
                b.status = r.get("status") or "Active"
                b.landlord = p["landlord"]
                b.company = company
                for field, key in (("area_name", "area_name"),
                                   ("zone_no", "zone_no"),
                                   ("street_no", "street_no"),
                                   ("building_no", "building_no"),
                                   ("kahramaa_account_no",
                                    "kahramaa_account_no")):
                    if r.get(key) and b.meta.has_field(field):
                        setattr(b, field, r[key])
                b.flags.ignore_permissions = True
                b.insert()
                made_b += 1

            if not frappe.db.exists("Head Lease", {"building": p["code"],
                                                   "docstatus": ["<", 2]}):
                h = frappe.new_doc("Head Lease")
                h.building = p["code"]
                h.landlord = p["landlord"]
                h.company = company
                h.status = "Active"
                h.start_date = p["start"]
                h.end_date = p["end"]
                h.annual_rent = p["annual"]
                h.payment_frequency = p["freq"]
                for field, key, cast in (
                        ("security_deposit", "security_deposit", float),
                        ("rent_free_days", "rent_free_days", int),
                        ("notice_period_days", "notice_period_days", int)):
                    if r.get(key) and h.meta.has_field(field):
                        setattr(h, field, cast(r[key]))
                if h.meta.has_field("auto_renew"):
                    h.auto_renew = int(r.get("auto_renew") or 0)
                h.flags.ignore_permissions = True
                h.insert()
                made_h += 1

            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            why = str(e).strip().splitlines()
            failed.append((p["code"], why[0][:90] if why else type(e).__name__))

    for code, why in failed:
        print("  ! %s: %s" % (code, why))
    print("  created %d building(s) and %d head lease(s)" % (made_b, made_h))
    if failed:
        print("  %d building(s) failed" % len(failed))
    print("  Now press Gate.")
    return {"buildings": made_b, "head_leases": made_h, "failed": len(failed)}


def gate():
    rows = C.rows(SOURCE)
    want = {r["building_code"]: r for r in rows if r.get("building_code")}

    on_site = set(frappe.get_all("Building", pluck="name"))
    missing = sorted(set(want) - on_site)
    extra = sorted(on_site - set(want))

    # every building must carry a cost centre. create_building_cost_center
    # gives up quietly after a msgprint if the company or the root cost centre
    # is not found, and a msgprint in a background worker goes nowhere anyone
    # reads. A building with no cost centre drops out of the spread rather than
    # reporting zero.
    no_cc, dead_cc = [], []
    for b in frappe.get_all("Building", fields=["name", "cost_center"]):
        if not b.cost_center:
            no_cc.append(b.name)
        elif not frappe.db.exists("Cost Center", b.cost_center):
            dead_cc.append(b.name)

    leased, wrong_rent, wrong_dates = [], [], []
    for code, r in want.items():
        hl = frappe.get_all("Head Lease", filters={"building": code},
                            fields=["name", "annual_rent", "start_date",
                                    "end_date"])
        if not hl:
            continue
        leased.append(code)
        h = hl[0]
        if int(h.annual_rent or 0) != int(float(r["annual_rent"])):
            wrong_rent.append("%s (%s vs %s)"
                              % (code, h.annual_rent, r["annual_rent"]))
        if str(h.start_date) != r["hl_start"] or str(h.end_date) != r["hl_end"]:
            wrong_dates.append(code)

    want_total = sum(int(float(r["annual_rent"])) for r in want.values())
    got_total = sum(int(h.annual_rent or 0) for h in
                    frappe.get_all("Head Lease", fields=["annual_rent"]))

    checks = [
        ("every building loaded", not missing,
         "%d of %d%s" % (len(on_site & set(want)), len(want),
                         "" if not missing else "; missing %s"
                         % ", ".join(missing[:4]))),
        ("no building the worksheet does not name", not extra,
         "none" if not extra else "extra: %s" % ", ".join(extra[:4])),
        ("every building has a live cost centre", not no_cc and not dead_cc,
         "all %d" % len(on_site) if not (no_cc or dead_cc)
         else "no cost centre: %s; dangling: %s"
              % (", ".join(no_cc[:3]) or "-", ", ".join(dead_cc[:3]) or "-")),
        ("every building has a head lease", len(leased) == len(want),
         "%d of %d" % (len(leased), len(want))),
        ("head-lease rent matches the worksheet", not wrong_rent,
         "all match" if not wrong_rent else "; ".join(wrong_rent[:3])),
        ("head-lease dates match the worksheet", not wrong_dates,
         "all match" if not wrong_dates
         else "differ: %s" % ", ".join(wrong_dates[:4])),
        ("annual rent reconciles to the riyal", want_total == got_total,
         "QAR %s on site vs QAR %s in the worksheet"
         % (f"{got_total:,}", f"{want_total:,}")),
    ]
    return C.gate_result(STAGE, checks)
