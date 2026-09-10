"""Stage 2 — buildings, and the head leases behind them.

Leases live in their own file because a building can have more than one.
DAJ-21 is the reason: the written agreement covers 8 flats at QAR 28,000 a
month, and the owner-rent register shows QAR 78,000 every month from November
2025, when the whole 25-flat building was taken on. One lease at either figure
is wrong for part of the term — 28,000 understates the cost by 600,000 a year,
78,000 overstates Aug-Oct by 150,000.

That error is worth understanding rather than only fixing. DAJ-21 showed a 246%
margin, three times the next best building, and read as the star of the estate.
It was an understated cost. The real margin is 24%, in line with everything
else, and the portfolio spread is QAR 196,650 a month rather than 246,650.

Not using `portfolio.onboard_building`: it creates a Head Lease only when
annual_rent and start_date are both truthy, and says nothing when it skips.
That is the silent path that left 22 buildings showing a placeholder end date
of 31 Jul 2027 last time.
"""

import frappe

from darkbrown.load import common as C

STAGE = "2"
BUILDINGS = "buildings.csv"
LEASES = "head_leases.csv"

# read from the doctype rather than typed from memory: the Select option is
# "Annual", and "Annually" would have been rejected by validation
FREQ = ("Monthly", "Quarterly", "Half Yearly", "Annual")

BUILDING_FIELDS = ("area_name", "zone_no", "street_no", "building_no",
                   "kahramaa_account_no")


def _why(e):
    text = (str(e) or "").strip() or type(e).__name__
    lines = text.splitlines()
    return (lines[0] if lines else type(e).__name__)[:90]


def _landlords():
    out = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        out[C.norm(s.supplier_name or s.name)] = s.name
    return out


def _resolve():
    brows, lrows = C.rows(BUILDINGS), C.rows(LEASES)
    landlords = _landlords()
    problems, seen, plan = [], {}, []

    for i, r in enumerate(brows, start=2):
        code = (r.get("building_code") or "").strip()
        if not code:
            problems.append(C.Problem(BUILDINGS, i, "building_code", code,
                                      "code_required", "blank building code"))
            continue
        if code in seen:
            problems.append(C.Problem(BUILDINGS, i, "building_code", code,
                                      "duplicate_in_file",
                                      "already used on row %d" % seen[code]))
            continue
        seen[code] = i
        ll = landlords.get(C.norm(r.get("landlord")))
        if not ll:
            problems.append(C.Problem(
                BUILDINGS, i, "landlord", r.get("landlord"), "landlord_missing",
                "no Supplier with that name — has Stage 1 run?"))
        plan.append({"row": i, "code": code, "landlord": ll, "raw": r,
                     "exists": frappe.db.exists("Building", code)})

    leases = []
    for i, r in enumerate(lrows, start=2):
        code = (r.get("building_code") or "").strip()
        if code not in seen:
            problems.append(C.Problem(LEASES, i, "building_code", code,
                                      "building_unknown",
                                      "no such building in %s" % BUILDINGS))
            continue
        start, end = r.get("hl_start"), r.get("hl_end")
        if not start or not end:
            problems.append(C.Problem(
                LEASES, i, "hl_start" if not start else "hl_end", start or end,
                "lease_dates_required", "a lease needs both dates"))
        elif end <= start:
            problems.append(C.Problem(LEASES, i, "hl_end", end,
                                      "lease_end_before_start",
                                      "end %s is not after start %s"
                                      % (end, start)))
        try:
            annual = int(float(r.get("annual_rent") or 0))
        except ValueError:
            annual = 0
            problems.append(C.Problem(LEASES, i, "annual_rent",
                                      r.get("annual_rent"),
                                      "annual_rent_number", "not a number"))
        if annual <= 0:
            problems.append(C.Problem(
                LEASES, i, "annual_rent", r.get("annual_rent"),
                "annual_rent_required",
                "no rent means no cost side, so no spread for this building"))
        freq = (r.get("payment_frequency") or "").strip()
        if freq not in FREQ:
            problems.append(C.Problem(LEASES, i, "payment_frequency", freq,
                                      "frequency_unknown",
                                      "must be one of %s" % ", ".join(FREQ)))
        leases.append({"row": i, "code": code,
                       "landlord": landlords.get(C.norm(r.get("landlord"))),
                       "annual": annual, "freq": freq, "start": start,
                       "end": end, "raw": r})

    for code in seen:
        if not any(l["code"] == code for l in leases):
            problems.append(C.Problem(
                LEASES, "-", "building_code", code, "no_lease_for_building",
                "no head lease — the cost side would be missing entirely"))

    live = {}
    for l in leases:
        if (l["raw"].get("status") or "") == "Active":
            if l["code"] in live:
                problems.append(C.Problem(
                    LEASES, l["row"], "status", "Active", "two_active_leases",
                    "%s already has an active lease on row %d — the monthly "
                    "cost would count twice" % (l["code"], live[l["code"]])))
            live[l["code"]] = l["row"]

    return plan, leases, problems


def _active_total(leases):
    return sum(l["annual"] for l in leases
               if (l["raw"].get("status") or "") == "Active")


def check():
    plan, leases, problems = _resolve()
    fresh = [p for p in plan if not p["exists"]]
    total = _active_total(leases)

    print("STAGE 2 CHECK — buildings and head leases")
    print("  %s: %d rows    %s: %d rows"
          % (BUILDINGS, len(plan), LEASES, len(leases)))
    print("  %d building(s) to create, %d already present"
          % (len(fresh), len(plan) - len(fresh)))
    print("  annual rent across active leases: QAR %s  (QAR %s a month)"
          % (f"{total:,}", f"{total / 12:,.0f}"))

    multi = {}
    for l in leases:
        multi[l["code"]] = multi.get(l["code"], 0) + 1
    for code in sorted(k for k, v in multi.items() if v > 1):
        print("  %s carries %d lease periods:" % (code, multi[code]))
        for l in [x for x in leases if x["code"] == code]:
            print("      %-8s %s to %s  QAR %s/yr"
                  % (l["raw"].get("status"), l["start"], l["end"],
                     f"{l['annual']:,}"))
            if l["raw"].get("note"):
                print("               %s" % l["raw"]["note"][:70])
    C.report(problems)
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "annual_rent": total,
            "problems": len(problems), "clean": not problems}


def _write(plan, leases, update_existing=False):
    company = C.company()
    made_b, made_h, touched, failed = 0, 0, 0, []

    for p in plan:
        r = p["raw"]
        try:
            if p["exists"]:
                if update_existing:
                    b = frappe.get_doc("Building", p["code"])
                    b.landlord = p["landlord"]
                    for field in BUILDING_FIELDS:
                        if r.get(field) and b.meta.has_field(field):
                            setattr(b, field, r[field])
                    b.flags.ignore_permissions = True
                    b.save()
                    touched += 1
            else:
                b = frappe.new_doc("Building")
                b.building_name = p["code"]
                b.status = r.get("status") or "Active"
                b.landlord = p["landlord"]
                b.company = company
                for field in BUILDING_FIELDS:
                    if r.get(field) and b.meta.has_field(field):
                        setattr(b, field, r[field])
                b.flags.ignore_permissions = True
                b.insert()
                made_b += 1
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            failed.append((p["code"], _why(e)))

    for l in leases:
        r = l["raw"]
        try:
            h = frappe.new_doc("Head Lease")
            h.building = l["code"]
            h.landlord = l["landlord"]
            h.company = company
            h.status = r.get("status") or "Active"
            h.start_date = l["start"]
            h.end_date = l["end"]
            h.annual_rent = l["annual"]
            h.payment_frequency = l["freq"]
            for field, cast in (("security_deposit", float),
                                ("rent_free_days", int),
                                ("notice_period_days", int)):
                if r.get(field) and h.meta.has_field(field):
                    setattr(h, field, cast(r[field]))
            if h.meta.has_field("auto_renew"):
                h.auto_renew = int(r.get("auto_renew") or 0)
            if r.get("note") and h.meta.has_field("notes"):
                h.notes = r["note"]
            h.flags.ignore_permissions = True
            h.insert()
            frappe.db.commit()
            made_h += 1
        except Exception as e:
            frappe.db.rollback()
            failed.append(("%s lease %s" % (l["code"], l["start"]), _why(e)))

    return made_b, made_h, touched, failed


def run():
    plan, leases, problems = _resolve()
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 2 refused: %d problem(s). Run Check."
                     % len(problems))

    existing = frappe.db.count("Head Lease")
    if existing:
        frappe.throw("%d head lease(s) already exist. Use Reload 2 to replace "
                     "them — running again would count the cost twice."
                     % existing)

    print("STAGE 2 RUN — buildings and head leases")
    made_b, made_h, _, failed = _write(plan, leases)
    for code, why in failed:
        print("  ! %s: %s" % (code, why))
    print("  created %d building(s) and %d head lease(s)" % (made_b, made_h))
    print("  Now press Gate.")
    return {"buildings": made_b, "head_leases": made_h, "failed": len(failed)}


def reload():
    """Replace the head leases from a corrected worksheet.

    Buildings are updated in place, never deleted: a building's name is its
    record name and every unit is named `{building}-{unit_no}`, so deleting one
    would take its units with it.

    Refuses once anything has been posted against a lease. Before the ledger a
    correction is a rewrite; after it, cancelling writes reversing entries and
    leaves the originals behind, which is how 9,958 GL rows became 17,303
    during the wipe.
    """
    for blocker in ("Head Lease Payment", "Cheque"):
        try:
            n = frappe.db.count(blocker)
        except Exception:
            continue
        if n:
            frappe.throw("%d %s record(s) exist. Replacing the leases now "
                         "would orphan them — correct the lease by hand."
                         % (n, blocker))

    plan, leases, problems = _resolve()
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 2 reload refused: %d problem(s)." % len(problems))

    print("STAGE 2 RELOAD — replacing the head leases")
    dropped = 0
    for name in frappe.get_all("Head Lease", pluck="name"):
        try:
            frappe.delete_doc("Head Lease", name, force=True,
                              ignore_permissions=True, delete_permanently=True)
            dropped += 1
        except Exception as e:
            print("  ! could not remove %s: %s" % (name, _why(e)))
    frappe.db.commit()
    print("  removed %d existing lease(s)" % dropped)

    made_b, made_h, touched, failed = _write(plan, leases, update_existing=True)
    for code, why in failed:
        print("  ! %s: %s" % (code, why))
    print("  %d building(s) created, %d updated, %d lease(s) written"
          % (made_b, touched, made_h))
    print("  Now press Gate.")
    return {"removed": dropped, "head_leases": made_h, "updated": touched}


def gate():
    plan, leases, _ = _resolve()
    want = {p["code"] for p in plan}
    on_site = set(frappe.get_all("Building", pluck="name"))
    missing = sorted(want - on_site)
    extra = sorted(on_site - want)

    no_cc, dead_cc = [], []
    for b in frappe.get_all("Building", fields=["name", "cost_center"]):
        if not b.cost_center:
            no_cc.append(b.name)
        elif not frappe.db.exists("Cost Center", b.cost_center):
            dead_cc.append(b.name)

    hl = frappe.get_all("Head Lease",
                        fields=["name", "building", "status", "annual_rent",
                                "start_date", "end_date"])
    by_building = {}
    for h in hl:
        by_building.setdefault(h.building, []).append(h)
    unleased = sorted(want - set(by_building))
    two_active = sorted(b for b, hs in by_building.items()
                        if len([h for h in hs if h.status == "Active"]) > 1)

    want_total = _active_total(leases)
    got_total = sum(int(h.annual_rent or 0) for h in hl if h.status == "Active")

    wrong = []
    for l in leases:
        match = [h for h in by_building.get(l["code"], [])
                 if str(h.start_date) == l["start"]]
        if not match:
            wrong.append("%s %s missing" % (l["code"], l["start"]))
        elif int(match[0].annual_rent or 0) != l["annual"] \
                or str(match[0].end_date) != l["end"]:
            wrong.append("%s %s differs" % (l["code"], l["start"]))

    checks = [
        ("every building loaded", not missing,
         "%d of %d" % (len(on_site & want), len(want)) +
         ("" if not missing else "; missing %s" % ", ".join(missing[:4]))),
        ("no building the worksheet does not name", not extra,
         "none" if not extra else ", ".join(extra[:4])),
        ("every building has a live cost centre", not no_cc and not dead_cc,
         "all %d" % len(on_site) if not (no_cc or dead_cc)
         else "no cost centre: %s; dangling: %s"
              % (", ".join(no_cc[:3]) or "-", ", ".join(dead_cc[:3]) or "-")),
        ("every building has at least one head lease", not unleased,
         "%d of %d" % (len(by_building), len(want)) +
         ("" if not unleased else "; %s" % ", ".join(unleased[:4]))),
        ("no building has two active leases", not two_active,
         "none" if not two_active
         else "cost counted twice for %s" % ", ".join(two_active[:3])),
        ("every lease period matches the worksheet", not wrong,
         "all %d match" % len(leases) if not wrong else "; ".join(wrong[:3])),
        ("active annual rent reconciles to the riyal", want_total == got_total,
         "QAR %s on site vs QAR %s in the worksheet"
         % (f"{got_total:,}", f"{want_total:,}")),
    ]
    return C.gate_result(STAGE, checks)
