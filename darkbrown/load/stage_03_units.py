"""Stage 3 — the units.

The unit list comes from the Revenue worksheet, not the Tenancy Master. Revenue
records every flat that has ever been charged rent, including the 98 whose
agreements were never written up; the Tenancy Master only knows the ones with
paperwork. Taking the smaller list would have quietly dropped a third of the
portfolio.

Every unit loads **Vacant**, never "Not Ready".

That is not a style choice. `TenancyAgreement._sync_unit_occupancy()` opens:

    current = frappe.db.get_value("Unit", self.unit, "status")
    if current in ("Not Ready", "Under Maintenance"):
        return

So a unit left at the doctype default of "Not Ready" never becomes Occupied,
however many live tenancies point at it. The portfolio would read 100% vacant
with 296 flats let. `onboard_building` defaults units to "Not Ready" too, which
is why this stage does not use it.

The flats that genuinely are empty need no special handling: they load Vacant
like everything else, Stage 5 flips only the ones with a live tenancy, and the
rest stay Vacant because nothing touched them.
"""

import frappe

from darkbrown.load import common as C

STAGE = "3"
SOURCE = "units.csv"

TYPES = ("", "Studio", "1BR", "2BR", "3BR", "4BR", "Penthouse", "Villa",
         "Shop", "Office", "Warehouse", "Labour Accommodation")


def _resolve(rows):
    buildings = set(frappe.get_all("Building", pluck="name"))
    plan, problems, seen = [], [], {}

    for i, r in enumerate(rows, start=2):
        code = (r.get("building") or "").strip()
        unit = (r.get("unit_no") or "").strip()

        if not code or not unit:
            problems.append(C.Problem(
                SOURCE, i, "building" if not code else "unit_no", code or unit,
                "key_required", "building and unit number are both needed"))
            continue
        if code not in buildings:
            problems.append(C.Problem(
                SOURCE, i, "building", code, "building_missing",
                "no Building with that code — has Stage 2 run?"))
            continue

        key = (code, unit)
        if key in seen:
            problems.append(C.Problem(
                SOURCE, i, "unit_no", unit, "duplicate_in_file",
                "%s already used on row %d" % (unit, seen[key])))
            continue
        seen[key] = i

        utype = (r.get("unit_type") or "").strip()
        if utype not in TYPES:
            problems.append(C.Problem(
                SOURCE, i, "unit_type", utype, "unit_type_unknown",
                "not one of the doctype's options"))

        status = (r.get("status") or "").strip()
        if status != "Vacant":
            problems.append(C.Problem(
                SOURCE, i, "status", status, "status_must_be_vacant",
                "'Not Ready' stops a tenancy ever marking the unit Occupied"))

        plan.append({"row": i, "building": code, "unit_no": unit,
                     "type": utype, "raw": r,
                     "exists": frappe.db.exists("Unit", "%s-%s" % (code, unit))})
    return plan, problems


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    fresh = [p for p in plan if not p["exists"]]

    per = {}
    for p in plan:
        per[p["building"]] = per.get(p["building"], 0) + 1

    print("STAGE 3 CHECK — units")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d unit(s) to create, %d already present"
          % (len(fresh), len(plan) - len(fresh)))
    print("  per building:")
    for code in sorted(per):
        print("      %-9s %3d" % (code, per[code]))
    typed = len([p for p in plan if p["type"]])
    print("  %d unit(s) carry a type, %d do not — the worksheet leaves most blank"
          % (typed, len(plan) - typed))
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
        frappe.throw("Stage 3 refused: %d problem(s). Run Check."
                     % len(problems))

    made, failed = 0, []
    print("STAGE 3 RUN — units")
    for p in plan:
        if p["exists"]:
            continue
        r = p["raw"]
        try:
            u = frappe.new_doc("Unit")
            u.building = p["building"]
            u.unit_no = p["unit_no"]
            u.status = "Vacant"
            if p["type"] and u.meta.has_field("unit_type"):
                u.unit_type = p["type"]
            rent = r.get("market_rent")
            if rent and u.meta.has_field("market_rent"):
                u.market_rent = float(rent)
            u.flags.ignore_permissions = True
            u.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            why = str(e).strip().splitlines()
            failed.append(("%s-%s" % (p["building"], p["unit_no"]),
                           why[0][:90] if why else type(e).__name__))

    if failed:
        C.report([C.Problem(SOURCE, "-", "unit", n, "insert_failed", w)
                  for n, w in failed])
    print("  created %d unit(s)" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def gate():
    rows = C.rows(SOURCE)
    want = {}
    for r in rows:
        want.setdefault(r["building"], set()).add(r["unit_no"])
    want_total = sum(len(v) for v in want.values())

    got = {}
    statuses = {}
    for u in frappe.get_all("Unit", fields=["name", "building", "unit_no",
                                            "status"]):
        got.setdefault(u.building, set()).add(u.unit_no)
        statuses[u.status] = statuses.get(u.status, 0) + 1
    got_total = sum(len(v) for v in got.values())

    short = []
    for code, units in sorted(want.items()):
        missing = units - got.get(code, set())
        if missing:
            short.append("%s missing %d" % (code, len(missing)))

    extra = sorted(set(got) - set(want))
    not_ready = statuses.get("Not Ready", 0)
    orphans = len([u for u in frappe.get_all("Unit", fields=["building"])
                   if not frappe.db.exists("Building", u.building)])

    # total_units is written by a hook off the real Unit rows. If it is still
    # zero the buildings screen shows an empty portfolio, and the shell builds
    # its unit list from that number.
    zero_count = [b.name for b in
                  frappe.get_all("Building", fields=["name", "total_units"])
                  if not b.total_units]

    checks = [
        ("every unit in the worksheet exists", not short,
         "%d of %d" % (got_total, want_total) +
         ("" if not short else "; " + ", ".join(short[:4]))),
        ("no building carries units it should not", not extra,
         "none" if not extra else ", ".join(extra[:4])),
        ("no unit points at a building that is gone", orphans == 0,
         "%d orphan(s)" % orphans),
        ("none left 'Not Ready'", not_ready == 0,
         "%d would never show Occupied" % not_ready if not_ready
         else "all %d are Vacant" % statuses.get("Vacant", 0)),
        ("building unit counts refreshed", not zero_count,
         "all set" if not zero_count
         else "%d building(s) still read 0: %s"
              % (len(zero_count), ", ".join(zero_count[:4]))),
    ]
    return C.gate_result(STAGE, checks)
