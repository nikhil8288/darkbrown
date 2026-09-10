"""Stage 5 — the tenancies.

This is the stage the portfolio numbers come from. Stages 1 to 4 built a set
of things; this one puts people in flats, and afterwards the occupancy figure
on the dashboard is real for the first time.

The acceptance test is not the row count. It is that **267 of the 282 units
flip to Occupied on their own**, because `_sync_unit_occupancy()` runs on save
and nothing here touches `Unit.status` directly. A load that creates every row
and leaves the portfolio Vacant has failed.

Three things this stage has to get right:

**The tenant link goes through match_key, not the name.** 61 of the 380
tenants were folded — `AISHA` is on the site under her short name but keyed as
`aisha sophia marie arciga flores`. Stage 4 spent a full rebuild on exactly
this mismatch: it planned by one key and looked the site up by another, so it
re-created 61 customers on every run and reported them missing on every gate.
`stage_04_tenants._keymap()` is imported here rather than reimplemented, so
the two stages cannot drift apart.

**A missing link is fatal, not skipped.** A tenancy that quietly fails to load
leaves its unit Vacant with somebody living in it, and the wrong occupancy
number goes to the MD. Every unresolved tenant, unit or date stops the run.

**An end date in the past marks a unit Vacant.** 171 tenancies have no written
agreement and their dates come from evidence — start is the first month rent
was charged, end is the last month charged for the 93 that ended. For the 78
still live the end date is rolled forward past the current month so they stay
Active. Too late is recoverable; too early empties a flat that is occupied.
"""

import frappe

from darkbrown.load import common as C
from darkbrown.load.stage_04_tenants import _keymap

STAGE = "5"
SOURCE = "tenancies.csv"

LIVE = ("Active", "Expiring")
STATUSES = ("Draft", "Pending Approval", "Active", "Expiring", "Expired",
            "Terminated")
MODES = ("Cheque", "Cash", "Transfer")
FREQUENCIES = ("Monthly", "Quarterly", "Half Yearly", "Annual")
ROUTES = ("", "Self Approved", "Routed for Approval")


def _date(value):
    """A date the doctype will accept, or None.

    The sentinel 2199-12-31 stood in for "no end date known" in two of the
    source workbooks. It must not reach the field — an agreement running to
    the year 2199 is not evidence of anything, and it hides the renewals that
    are genuinely due.
    """
    text = str(value or "").strip()
    if not text or text.startswith("2199"):
        return None
    try:
        return frappe.utils.getdate(text)
    except Exception:
        return None


def _money(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _units():
    """Every unit on the site, by folded label, plus the superseded ones.

    14 unit labels were renumbered. Revenue was booked against the old number,
    so a tenancy row may still carry it. `unit_aliases.csv` maps them; the old
    label resolves to the unit that replaced it rather than failing the row.
    """
    live = {}
    for u in frappe.get_all("Unit", fields=["name", "building", "unit_no"]):
        live[(u.building, C.unit_key(u.unit_no))] = u.name
    try:
        for a in C.rows("unit_aliases.csv"):
            key = (a["building"], C.unit_key(a["old_unit_no"]))
            target = live.get((a["building"], C.unit_key(a["unit_no"])))
            if target and key not in live:
                live[key] = target
    except Exception:
        pass                    # the alias file is optional, the units are not
    return live


def _resolve(rows):
    keymap = _keymap(C.rows("tenants.csv"))
    tenants = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        n = C.norm(c.customer_name or c.name)
        tenants[keymap.get(n, n)] = c.name

    units = _units()
    existing = {}
    for t in frappe.get_all("Tenancy Agreement",
                            fields=["name", "unit", "tenant", "start_date"]):
        existing[(t.unit, str(t.start_date))] = t.name

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        key = (r.get("tenancy_key") or "").strip()
        tkey = (r.get("match_key") or "").strip()
        building = (r.get("building") or "").strip()
        unit_no = (r.get("unit_no") or "").strip()

        def bad(column, value, rule, message):
            problems.append(C.Problem(SOURCE, i, column, value, rule, message))

        if key and key in seen:
            bad("tenancy_key", key, "duplicate_in_file",
                "same tenancy as row %d" % seen[key])
            continue
        if key:
            seen[key] = i

        tenant = tenants.get(tkey)
        if not tenant:
            bad("match_key", tkey, "tenant_unresolved",
                "no Customer under this key — stage 4 must be gated first")

        unit = units.get((building, C.unit_key(unit_no)))
        if not unit:
            bad("unit_no", "%s %s" % (building, unit_no), "unit_unresolved",
                "no Unit on the site, and no alias points at one")

        start = _date(r.get("start_date"))
        end = _date(r.get("end_date"))
        if not start:
            bad("start_date", r.get("start_date"), "start_required",
                "the doctype requires it and evidence must supply it")
        if not end:
            bad("end_date", r.get("end_date"), "end_required",
                "blank or sentinel — a rolled-forward date is required")
        if start and end and end < start:
            bad("end_date", r.get("end_date"), "end_before_start",
                "ends before it begins")

        status = (r.get("status") or "").strip()
        if status not in STATUSES:
            bad("status", status, "status_unknown",
                "not one of the doctype's options")

        rent = _money(r.get("monthly_rent"))
        free = str(r.get("rent_free") or "").strip() == "1"
        if rent is None:
            bad("monthly_rent", r.get("monthly_rent"), "rent_not_a_number",
                "could not be read as an amount")
        elif rent <= 0 and status in LIVE and not free:
            bad("monthly_rent", rent, "live_without_rent",
                "a live tenancy charging nothing will not reconcile")

        mode = (r.get("payment_mode") or "Cheque").strip()
        if mode not in MODES:
            bad("payment_mode", mode, "mode_unknown",
                "not one of the doctype's options")
        freq = (r.get("payment_frequency") or "Monthly").strip()
        if freq not in FREQUENCIES:
            bad("payment_frequency", freq, "frequency_unknown",
                "not one of the doctype's options")
        route = (r.get("activation_route") or "").strip()
        if route not in ROUTES:
            bad("activation_route", route, "route_unknown",
                "not one of the doctype's options")

        # An end date already past marks the unit Vacant the moment it saves.
        if status in LIVE and end and end < frappe.utils.getdate():
            bad("end_date", r.get("end_date"), "live_but_expired",
                "status is live but the date has passed — the unit would go "
                "Vacant with a tenant in it")

        plan.append({"row": i, "key": key, "raw": r, "tenant": tenant,
                     "unit": unit, "start": start, "end": end,
                     "status": status, "rent": rent or 0.0,
                     "existing": existing.get((unit, str(start)))})
    return plan, problems


def _describe(plan):
    live = [p for p in plan if p["status"] in LIVE]
    return {
        "rows": len(plan),
        "live": len(live),
        "units_live": len(set(p["unit"] for p in live if p["unit"])),
        "papers": len([p for p in plan
                       if p["raw"].get("has_agreement") == "1"]),
        "rent": sum(p["rent"] for p in live),
    }


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    d = _describe(plan)
    fresh = [p for p in plan if not p["existing"]]
    routed = len([p for p in plan
                  if p["raw"].get("activation_route") == "Routed for Approval"])

    print("STAGE 5 CHECK — tenancies")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d to create, %d already on the site"
          % (len(fresh), len(plan) - len(fresh)))
    print("  %d live, covering %d of %d units"
          % (d["live"], d["units_live"], frappe.db.count("Unit")))
    print("  monthly rent on the live ones: QAR %s"
          % frappe.utils.fmt_money(d["rent"], currency="QAR"))
    print("  %d have an agreement on file, %d are on evidence alone"
          % (d["papers"], len(plan) - d["papers"]))
    print("  %d routed for approval" % routed)
    free = [p for p in plan if str(p["raw"].get("rent_free") or "") == "1"]
    if free:
        print("  %d rent-free — charging nothing while occupied, awaiting "
              "Anoop's treatment:" % len(free))
        for p in free[:6]:
            print("        %s %s from %s"
                  % (p["raw"].get("building"), p["raw"].get("unit_no"),
                     p["raw"].get("start_date")))
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
        frappe.throw("Stage 5 refused: %d problem(s). Run Check." % len(problems))

    company = C.company()
    made, failed = 0, []
    print("STAGE 5 RUN — tenancies")

    for p in plan:
        if p["existing"]:
            continue
        r = p["raw"]
        try:
            t = frappe.new_doc("Tenancy Agreement")
            t.tenant = p["tenant"]
            t.unit = p["unit"]
            t.building = (r.get("building") or "").strip()
            t.company = company
            t.status = p["status"]
            t.start_date = p["start"]
            t.end_date = p["end"]
            t.monthly_rent = p["rent"]
            t.security_deposit = _money(r.get("security_deposit")) or 0.0
            t.payment_mode = (r.get("payment_mode") or "Cheque").strip()
            t.payment_frequency = (r.get("payment_frequency")
                                   or "Monthly").strip()
            if r.get("activation_route"):
                t.activation_route = r["activation_route"].strip()
            if r.get("missing_items"):
                t.missing_items = r["missing_items"]
            if r.get("qid_number"):
                t.qid_number = str(r["qid_number"])[:140]
            if r.get("mobile_no"):
                t.mobile_no = str(r["mobile_no"])[:140]
            if r.get("notes"):
                t.notes = r["notes"]
            t.flags.ignore_permissions = True
            t.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            failed.append(("%s %s" % (r.get("building"), r.get("unit_no")),
                           (text.splitlines() or ["?"])[0][:90]))

    if failed:
        C.report([C.Problem(SOURCE, "-", "unit_no", n, "insert_failed", w)
                  for n, w in failed])
    occupied = frappe.db.count("Unit", {"status": "Occupied"})
    print("  created %d tenancy agreement(s)" % made)
    print("  %d of %d units are now Occupied"
          % (occupied, frappe.db.count("Unit")))
    if failed:
        print("  %d row(s) failed — the units behind them still read Vacant."
              % len(failed))
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed), "occupied": occupied}


def reload():
    """Re-read the worksheet, adding what is missing.

    Nothing is deleted. Once rent is invoiced against an agreement the money
    hangs off it, and removing the agreement orphans the receivable.
    """
    live = frappe.db.count("Sales Invoice")
    if live:
        frappe.throw("%d invoice(s) are posted against these tenancies. "
                     "Correct them by hand rather than reloading." % live)
    print("STAGE 5 RELOAD — tenancies")
    return run()


def gate():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    d = _describe(plan)

    on_site = frappe.db.count("Tenancy Agreement")
    live_site = frappe.db.count("Tenancy Agreement", {"status": ["in", LIVE]})
    units = frappe.db.count("Unit")
    occupied = frappe.db.count("Unit", {"status": "Occupied"})
    not_ready = frappe.db.count("Unit", {"status": "Not Ready"})

    orphan_tenant = len([t for t in frappe.get_all(
        "Tenancy Agreement", fields=["name", "tenant"])
        if not frappe.db.exists("Customer", t.tenant)])
    orphan_unit = len([t for t in frappe.get_all(
        "Tenancy Agreement", fields=["name", "unit"])
        if not frappe.db.exists("Unit", t.unit)])

    stale = frappe.db.count("Tenancy Agreement", {
        "status": ["in", LIVE], "end_date": ["<", frappe.utils.today()]})

    checks = [
        ("every tenancy in the worksheet exists", on_site == len(plan),
         "%d on site vs %d expected" % (on_site, len(plan))),
        ("the live ones match the worksheet", live_site == d["live"],
         "%d live vs %d expected" % (live_site, d["live"])),
        ("units flipped to Occupied on their own",
         occupied == d["units_live"],
         "%d of %d Occupied, expected %d"
         % (occupied, units, d["units_live"])),
        ("no tenancy points at a tenant that is gone", not orphan_tenant,
         "%d orphan(s)" % orphan_tenant),
        ("no tenancy points at a unit that is gone", not orphan_unit,
         "%d orphan(s)" % orphan_unit),
        ("no live tenancy has already ended", not stale,
         "none" if not stale else
         "%d live with an end date in the past" % stale),
        ("no unit left 'Not Ready'", not not_ready,
         "none" if not not_ready else
         "%d — these can never be marked Occupied" % not_ready),
        ("the worksheet still resolves cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
