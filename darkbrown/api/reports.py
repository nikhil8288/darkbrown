"""The nine standard report packs, read off live records.

The Reports screen has always been a design with nothing behind it. It listed
nine packs, each opening a form that collected a date range and a format and
then produced a toast saying the report had been generated. Live, the whole
screen was replaced by the NOT WIRED card, which was the honest thing to do
while no server existed.

This is that server. It writes nothing. Every pack is a query over records that
already exist - the ledger for the money, the portfolio doctypes for everything
else - and every pack returns the same shape, so the screen renders all nine
through one path:

    {"key", "title", "columns", "rows", "totals", "note", "count"}

`columns` carry a type so the screen knows how to align and format them, and
`totals` is a sparse row keyed by column, so a pack that has nothing to total
simply omits it rather than sending a row of zeroes.

WHAT "NO DATA" MEANS

A pack whose source is empty returns an empty `rows` and says why in `note`.
That is different from a pack that is not built, and the two must not look the
same on screen: "no cheques have been recorded yet" is a fact about the
business, "reporting has not been built" was a fact about the software. Only
the first one can appear now.

WHAT IS DELIBERATELY NOT HERE

Per-unit arbitrage spread. Rent is known per unit; head-lease cost is known per
building and there is no agreed rule for apportioning it - by unit count, by
floor area, by rent share, all defensible and all different. Inventing one
would make every per-unit margin in the portfolio a number nobody had decided.
The spread pack reports per building, and lists unit revenue beneath it without
pretending to a unit-level margin. That is a decision for Anoop, and when it is
made it is a few lines here.
"""
import datetime
from collections import defaultdict

import frappe
from frappe.utils import add_days, flt, get_last_day, getdate, today

from darkbrown.guards import ACC, GM, MD, guard

#: Every pack: key, title, one-line description, and what it reads.
CATALOGUE = [
    ("pl_by_building", "Monthly P&L by building",
     "Revenue, head-lease cost and net margin, by building and month",
     "Sales and Purchase Invoices, by cost centre"),
    ("spread", "Arbitrage spread analysis",
     "Rent billed against head-lease cost, per building, over the window",
     "Rental-income ledger and Head Lease records"),
    ("arrears", "Arrears ageing",
     "0-30 / 31-60 / 61-90 / 90+ with tenant and unit detail",
     "Unpaid Sales Invoices"),
    ("cheques", "Cheque register",
     "Every cheque by status, bank and maturity",
     "Cheque records"),
    ("occupancy", "Occupancy and vacancy",
     "Occupied, vacant days and the rent that vacancy costs",
     "Units and Tenancy Agreements"),
    ("renewals", "Renewal pipeline",
     "Agreements expiring in the window, with rent and notice dates",
     "Tenancy Agreements"),
    ("deposits", "Deposit liability",
     "Deposits held against live agreements, and what is refundable",
     "Security Deposits and Tenancy Agreements"),
    ("utilities", "Utility recovery",
     "Billed against recovered, by building",
     "Utility Bills"),
    ("audit", "Audit trail",
     "Who changed what, on the records that carry money",
     "Frappe's own Version log"),
]

_TITLES = {k: t for k, t, _d, _s in CATALOGUE}


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company"))


def _window(frm, to):
    to = getdate(to) if to else getdate(today())
    frm = getdate(frm) if frm else getdate(to).replace(day=1)
    return str(frm), str(to)


def _months(frm, to):
    out, d = [], getdate(frm).replace(day=1)
    last = getdate(to).replace(day=1)
    while d <= last and len(out) < 120:
        out.append(d)
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return out


def _unit_no(unit):
    """Tenancy Agreement links to a Unit and carries no unit number of its own.
    Asking for one is an unknown column, which raises rather than returning
    blank - so the number is read from the Unit."""
    if not unit:
        return ""
    return frappe.db.get_value("Unit", unit, "unit_no") or unit


def _buildings():
    return frappe.get_all("Building", pluck="name")


def _col(key, label, kind="text"):
    return {"key": key, "label": label, "type": kind}


def _pack(key, columns, rows, totals=None, note=""):
    return {"key": key, "title": _TITLES.get(key, key), "columns": columns,
            "rows": rows, "totals": totals or {}, "note": note,
            "count": len(rows)}


# --------------------------------------------------------------------- packs

def _pl_by_building(frm, to, building=None):
    company = _company()
    cost_centres = {b.cost_center: b.name for b in frappe.get_all(
        "Building", fields=["name", "cost_center"]) if b.cost_center}
    if building:
        cost_centres = {k: v for k, v in cost_centres.items() if v == building}

    rows_by = defaultdict(
        lambda: {"income": 0.0, "expense": 0.0, "head_lease": 0.0})
    gl = frappe.get_all(
        "GL Entry",
        filters={"is_cancelled": 0, "company": company,
                 "posting_date": ["between", [frm, to]]},
        fields=["account", "cost_center", "debit", "credit", "posting_date"],
        limit=50000)
    accounts = frappe.get_all(
        "Account", filters={"company": company},
        fields=["name", "root_type", "account_name"])
    roots = {a.name: a.root_type for a in accounts}
    head_lease_accounts = {
        a.name for a in accounts if a.account_name == "Head Lease Rent"}

    for e in gl:
        b = cost_centres.get(e.cost_center)
        if not b:
            continue
        root = roots.get(e.account)
        month = str(getdate(e.posting_date).replace(day=1))
        if root == "Income":
            rows_by[(b, month)]["income"] += flt(e.credit) - flt(e.debit)
        elif root == "Expense":
            amount = flt(e.debit) - flt(e.credit)
            rows_by[(b, month)]["expense"] += amount
            if e.account in head_lease_accounts:
                rows_by[(b, month)]["head_lease"] += amount

    leases = defaultdict(list)
    for lease in frappe.get_all(
            "Head Lease",
            filters={"status": ["in", ("Active", "Expiring", "Expired")]},
            fields=["building", "start_date", "end_date", "annual_rent",
                    "rent_free_days"]):
        leases[lease.building].append(lease)

    def expects_head_lease_cost(building_name, month):
        month_start = getdate(month)
        month_end = get_last_day(month_start)
        for lease in leases.get(building_name, []):
            charge_start = add_days(
                getdate(lease.start_date), int(lease.rent_free_days or 0))
            if (flt(lease.annual_rent) > 0 and charge_start <= month_end
                    and getdate(lease.end_date) >= month_start):
                return True
        return False

    # Overhead does not post to a building and never should; it is divided
    # here so the margin is what the building actually earns the company
    # rather than what it earns before anyone is paid to run it.
    from darkbrown.utils import allocation
    try:
        alloc = allocation.allocate(frm, to).get("by_building_month") or {}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Overhead allocation skipped")
        alloc = {}

    keys = set(rows_by) | {(k.split("|")[0], k.split("|")[1] + "-01")
                           for k in alloc}
    if building:
        keys = {k for k in keys if k[0] == building}

    rows = []
    for (b, month) in sorted(keys):
        v = rows_by.get((b, month),
                        {"income": 0.0, "expense": 0.0, "head_lease": 0.0})
        overhead = flt(alloc.get("%s|%s" % (b, month[:7]), 0.0))
        expects_cost = expects_head_lease_cost(b, month)
        missing_posting = v["income"] > 0 and abs(v["head_lease"]) < 0.005
        missing_cost = missing_posting and expects_cost
        missing_lease = missing_posting and not expects_cost
        incomplete_row = missing_cost or missing_lease
        net = (None if incomplete_row
               else v["income"] - v["expense"] - overhead)
        rows.append({"building": b, "month": month[:7],
                     "income": round(v["income"], 2),
                     "expense": round(v["expense"], 2),
                     "overhead": round(overhead, 2),
                     "cost_status": ("Missing head-lease cost" if missing_cost
                                     else "No chargeable head lease" if missing_lease
                                     else "Complete" if v["income"]
                                     else "No revenue"),
                     "net": round(net, 2) if net is not None else None,
                     "margin": (round(net / v["income"] * 100, 1)
                                if v["income"] and net is not None else None)})

    cols = [_col("building", "Building"), _col("month", "Month"),
            _col("income", "Revenue", "money"),
            _col("expense", "Direct cost", "money"),
            _col("overhead", "Allocated overhead", "money"),
            _col("cost_status", "Cost status"),
            _col("net", "Net", "money"), _col("margin", "Margin", "percent")]
    inc = sum(r["income"] for r in rows)
    exp = sum(r["expense"] for r in rows)
    ovh = sum(r["overhead"] for r in rows)
    incomplete = any(r["cost_status"] in
                     ("Missing head-lease cost", "No chargeable head lease")
                     for r in rows)
    totals = {"income": round(inc, 2), "expense": round(exp, 2),
              "overhead": round(ovh, 2),
              "cost_status": "Incomplete" if incomplete else "Complete",
              "net": None if incomplete else round(inc - exp - ovh, 2),
              "margin": (None if incomplete or not inc
                         else round((inc - exp - ovh) / inc * 100, 1))}
    note = ("Direct cost is what posted to the building's own cost centre. "
            "Allocated overhead is the company's common cost divided by "
            "head-lease weight across the buildings that were live that "
            "month, in whole riyals - it is not in the ledger against this "
            "building and never will be, because it is not this building's "
            "cost. It is here because a margin that ignores it flatters every "
            "building. ")
    if not rows:
        note = ("Nothing posted against a building cost centre in this window, "
                "and no overhead to divide. A posting with no cost centre "
                "cannot be attributed to a building and is left out rather "
                "than spread across them.")
    elif incomplete:
        note += ("One or more revenue rows either have no chargeable Head "
                 "Lease record or have no Head Lease Rent posting for an "
                 "active lease. Their net and margin, and the report totals, "
                 "are withheld rather than presenting revenue less incomplete "
                 "cost as profit.")
    return _pack("pl_by_building", cols, rows, totals, note)


def _spread(frm, to, building=None):
    company = _company()
    months = _months(frm, to)
    leases = frappe.get_all(
        "Head Lease",
        filters={"status": ["in", ("Active", "Expiring", "Expired")]},
        fields=["building", "monthly_rent", "annual_rent", "start_date",
                "end_date", "rent_free_days"])

    # A tenancy invoice can also carry maintenance and utility recoveries.
    # Grand total is therefore not sublease rent. Read only the Rental Income
    # ledger postings so recovery-only invoices and recharge lines cannot
    # inflate the arbitrage spread.
    rental_accounts = frappe.get_all(
        "Account", filters={"company": company,
                            "account_name":
                                ["in", ("Rental Income", "Rent Income")],
                            "is_group": 0},
        pluck="name")
    billed = defaultdict(float)
    for gle in frappe.get_all(
            "GL Entry", filters={"is_cancelled": 0, "company": company,
                                 "account": ["in", rental_accounts],
                                 "posting_date": ["between", [frm, to]]},
            fields=["credit", "debit", "cost_center"], limit=50000):
        billed[gle.cost_center] += flt(gle.credit) - flt(gle.debit)
    posted_cost = defaultdict(float)
    for pi in frappe.get_all(
            "Purchase Invoice", filters={"docstatus": 1, "company": company,
                                         "posting_date": ["between", [frm, to]],
                                         "custom_landlord_contract":
                                             ["is", "set"]},
            fields=["grand_total", "cost_center"], limit=20000):
        posted_cost[pi.cost_center] += flt(pi.grand_total)
    by_cc = {b.cost_center: b.name for b in frappe.get_all(
        "Building", fields=["name", "cost_center"]) if b.cost_center}

    from darkbrown.api.finance import (
        _head_lease_accrual_window, _prorated_monthly)
    rows = []
    for b in sorted({x.building for x in leases} | set(by_cc.values())):
        if building and b != building:
            continue
        rent = sum(v for cc, v in billed.items() if by_cc.get(cc) == b)
        accrued_cost = 0.0
        for lease in [x for x in leases if x.building == b]:
            monthly = flt(lease.monthly_rent or flt(lease.annual_rent) / 12.0)
            for m in months:
                window = _head_lease_accrual_window(lease, m)
                if window:
                    accrued_cost += _prorated_monthly(monthly, *window)
        posted = sum(v for cc, v in posted_cost.items() if by_cc.get(cc) == b)
        units = frappe.db.count("Unit", {"building": b})
        gap = accrued_cost - posted
        missing_lease = (accrued_cost <= 0.005
                         and (rent > 0.005 or posted > 0.005))
        missing_posting = accrued_cost > 0.005 and abs(gap) > 0.005
        incomplete = missing_lease or missing_posting
        rows.append({"building": b, "units": units,
                     "rent": round(rent, 2), "cost": round(posted, 2),
                     "cost_status": ("No chargeable head lease" if missing_lease
                                     else "Head-lease cost not fully posted"
                                     if missing_posting else "Complete"),
                     "spread": (None if incomplete
                                else round(rent - posted, 2)),
                     "margin": (None if incomplete or not rent else
                                round((rent - posted) / rent * 100, 1)),
                     "accrued": round(accrued_cost, 2),
                     "gap": round(gap, 2),
                     "per_unit": (None if incomplete or not units else
                                  round((rent - posted) / units, 2))})

    cols = [_col("building", "Building"), _col("units", "Units", "number"),
            _col("rent", "Sublease revenue", "money"),
            _col("cost", "Head-lease cost", "money"),
            _col("cost_status", "Cost status"),
            _col("spread", "Spread", "money"),
            _col("margin", "Margin", "percent"),
            _col("accrued", "Cost accrued", "money"),
            _col("gap", "Not yet posted", "money"),
            _col("per_unit", "Spread per unit", "money")]
    rent = sum(r["rent"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    accrued = sum(r["accrued"] for r in rows)
    incomplete = any(r["cost_status"] != "Complete" for r in rows)
    totals = {"units": sum(r["units"] for r in rows),
              "rent": round(rent, 2), "cost": round(cost, 2),
              "cost_status": "Incomplete" if incomplete else "Complete",
              "spread": None if incomplete else round(rent - cost, 2),
              "margin": (None if incomplete or not rent
                         else round((rent - cost) / rent * 100, 1)),
              "accrued": round(accrued, 2), "gap": round(accrued - cost, 2)}
    gap = round(accrued - cost, 2)
    note = ("Head-lease cost is what actually posted. Cost accrued is what "
            "the head leases say "
            "is owed across the window; the gap between them is rent that has "
            "not been invoiced by the landlord yet.")
    if incomplete:
        note += (" Spread, margin and per-unit spread are withheld wherever "
                 "the chargeable lease schedule is absent or its accrued cost "
                 "has not been fully posted, and the totals are withheld too.")
    if gap:
        note += (" %s is accrued and not posted - check the landlord invoices "
                 "for the months at the end of the window." % format(gap, ",.2f"))
    note += (" Spread per unit divides the building's spread by its unit count."
             " It is not a per-unit margin, which would need an agreed "
             "apportionment rule.")
    return _pack("spread", cols, rows, totals, note)


def _arrears(frm, to, building=None):
    as_on = getdate(to)
    buildings = _buildings()
    filters = {"docstatus": 1, "outstanding_amount": [">", 0],
               "posting_date": ["<=", str(as_on)]}
    if building:
        cost_center = frappe.db.get_value("Building", building, "cost_center")
        if not cost_center:
            return _pack(
                "arrears", [], [], {},
                "%s has no cost centre, so its receivables cannot be scoped."
                % building)
        filters["cost_center"] = cost_center
    rows = []
    for si in frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=["name", "customer", "posting_date", "due_date",
                    "outstanding_amount", "grand_total", "cost_center",
                    "remarks", "custom_rental_agreement"], limit=20000):
        due = getdate(si.due_date or si.posting_date)
        age = (as_on - due).days
        bucket = ("current" if age <= 0 else "b30" if age <= 30
                  else "b60" if age <= 60 else "b90" if age <= 90 else "b90p")
        # The loader writes "... | AK-12 G-01B | ..." into remarks. Matching a
        # real building name is exact; guessing at the shape of the segment is
        # not, and would mislabel every invoice from a differently named one.
        unit = ""
        if si.custom_rental_agreement:
            unit_name = frappe.db.get_value(
                "Tenancy Agreement", si.custom_rental_agreement, "unit")
            if unit_name:
                unit_row = frappe.db.get_value(
                    "Unit", unit_name, ["building", "unit_no"], as_dict=True)
                if unit_row:
                    unit = "%s %s" % (unit_row.building,
                                      unit_row.unit_no or unit_name)
        for part in (si.remarks or "").split("|"):
            if unit:
                break
            part = part.strip()
            if any(part.startswith(b + " ") or part == b for b in buildings):
                unit = part
                break
        row = {"tenant": frappe.db.get_value("Customer", si.customer,
                                             "customer_name") or si.customer,
               "unit": unit, "invoice": si.name, "due": str(due),
               "age": age if age > 0 else 0,
               "current": 0.0, "b30": 0.0, "b60": 0.0, "b90": 0.0, "b90p": 0.0,
               "total": round(flt(si.outstanding_amount), 2)}
        row[bucket] = round(flt(si.outstanding_amount), 2)
        rows.append(row)
    rows.sort(key=lambda r: (-r["age"], r["tenant"]))

    cols = [_col("tenant", "Tenant"), _col("unit", "Unit"),
            _col("invoice", "Invoice"), _col("due", "Due"),
            _col("age", "Days", "number"),
            _col("current", "Not yet due", "money"),
            _col("b30", "0-30", "money"), _col("b60", "31-60", "money"),
            _col("b90", "61-90", "money"), _col("b90p", "90+", "money"),
            _col("total", "Total", "money")]
    totals = {k: round(sum(r[k] for r in rows), 2)
              for k in ("current", "b30", "b60", "b90", "b90p", "total")}
    note = (("Point-in-time receivables as at %s; the From date does not "
             "exclude older unpaid invoices." % as_on) if rows else
            "Nothing is outstanding as at %s." % as_on)
    return _pack("arrears", cols, rows, totals, note)


def _cheques(frm, to, building=None):
    filters = {"cheque_date": ["between", [frm, to]]}
    if building:
        filters["building"] = building
    rows = []
    for c in frappe.get_all(
            "Cheque", filters=filters,
            fields=["name", "direction", "party", "bank", "cheque_no",
                    "cheque_date", "amount", "status", "building", "unit"],
            order_by="cheque_date", limit=20000):
        amount = round(flt(c.amount), 2)
        rows.append({"cheque": c.name, "direction": c.direction,
                     "party": c.party, "bank": c.bank, "no": c.cheque_no,
                     "date": str(c.cheque_date), "building": c.building,
                     "unit": c.unit, "status": c.status,
                     "incoming": amount if c.direction == "Incoming" else None,
                     "outgoing": amount if c.direction == "Outgoing" else None})
    cols = [_col("cheque", "Ref"), _col("direction", "Direction"),
            _col("party", "Party"), _col("bank", "Bank"), _col("no", "No"),
            _col("date", "Maturity"), _col("building", "Building"),
            _col("unit", "Unit"), _col("status", "Status"),
            _col("incoming", "Incoming", "money"),
            _col("outgoing", "Outgoing", "money")]
    totals = {
        "incoming": round(sum(r["incoming"] or 0 for r in rows), 2),
        "outgoing": round(sum(r["outgoing"] or 0 for r in rows), 2),
    }
    note = "" if rows else (
        "No cheques with a maturity date in this window. Historical rent was "
        "loaded as receipts rather than as individual cheques, so the register "
        "fills from the first live PDC batch onward.")
    return _pack("cheques", cols, rows, totals, note)


def _occupancy(frm, to, building=None):
    frm_d, to_d = getdate(frm), getdate(to)
    span = (to_d - frm_d).days + 1
    filters = {} if not building else {"building": building}
    units = frappe.get_all("Unit", filters=filters,
                           fields=["name", "building", "unit_no", "status",
                                   "unit_type", "asking_rent"],
                           order_by="building, unit_no", limit=5000)
    tens = defaultdict(list)
    for t in frappe.get_all("Tenancy Agreement",
                            filters={"docstatus": ["<", 2],
                                     "status": ["in", (
                                         "Active", "Expiring", "Expired")]},
                            fields=["unit", "start_date", "end_date",
                                    "monthly_rent", "status"], limit=20000):
        tens[t.unit].append(t)

    rows = []
    for u in units:
        covered = set()
        rent = 0.0
        for t in tens.get(u.name, []):
            s, e = getdate(t.start_date), getdate(t.end_date)
            s, e = max(s, frm_d), min(e, to_d)
            d = s
            while d <= e:
                covered.add(d)
                d = add_days(d, 1)
            if getdate(t.end_date) >= to_d >= getdate(t.start_date):
                rent = flt(t.monthly_rent)
        occupied_days = len(covered)
        void_days = span - occupied_days
        benchmark = flt(u.asking_rent or rent)
        missing_rate = void_days > 0 and benchmark <= 0
        rows.append({"building": u.building, "unit": u.unit_no,
                     "type": u.unit_type or "", "status": u.status,
                     "occupied": occupied_days, "void": void_days,
                     "pct": round(occupied_days / span * 100, 1)
                     if span else None,
                     "rent": round(rent, 2),
                     "valuation": "Rate missing" if missing_rate else "Complete",
                     "lost": (None if missing_rate else
                              round(void_days / 30.0 * benchmark, 2))})
    cols = [_col("building", "Building"), _col("unit", "Unit"),
            _col("type", "Type"), _col("status", "Current status"),
            _col("occupied", "Occupied days", "number"),
            _col("void", "Vacant days", "number"),
            _col("pct", "Occupancy", "percent"),
            _col("rent", "Current rent", "money"),
            _col("valuation", "Vacancy valuation"),
            _col("lost", "Rent lost to vacancy", "money")]
    occ = sum(r["occupied"] for r in rows)
    tot = span * len(rows)
    incomplete = any(r["valuation"] == "Rate missing" for r in rows)
    totals = {"occupied": occ, "void": sum(r["void"] for r in rows),
              "pct": round(occ / tot * 100, 1) if tot else None,
              "rent": round(sum(r["rent"] for r in rows), 2),
              "valuation": "Incomplete" if incomplete else "Complete",
              "lost": (None if incomplete else
                       round(sum(r["lost"] or 0 for r in rows), 2))}
    return _pack("occupancy", cols, rows, totals,
                 "Rent lost to vacancy values a vacant month at the unit's asking "
                 "rent, falling back to its current rent where no asking rent "
                 "is set. A missing rate is shown as unknown and withholds the "
                 "total rather than valuing vacancy at zero. It is an "
                 "opportunity figure, not a ledger one.")


def _renewals(frm, to, building=None):
    filters = {"docstatus": ["<", 2],
               "status": ["in", ("Active", "Expiring", "Expired")],
               "end_date": ["between", [frm, to]]}
    if building:
        filters["building"] = building
    rows = []
    for t in frappe.get_all(
            "Tenancy Agreement", filters=filters,
            fields=["name", "tenant", "building", "unit",
                    "start_date", "end_date", "monthly_rent", "status",
                    "notice_days", "auto_renew"],
            order_by="end_date", limit=20000):
        end = getdate(t.end_date)
        rows.append({"agreement": t.name,
                     "tenant": frappe.db.get_value("Customer", t.tenant,
                                                   "customer_name") or t.tenant,
                     "building": t.building, "unit": _unit_no(t.unit),
                     "start": str(t.start_date), "end": str(end),
                     "days": (end - getdate(today())).days,
                     "notice_by": str(add_days(end, -(t.notice_days or 0))),
                     "rent": round(flt(t.monthly_rent), 2),
                     "auto": "Yes" if t.auto_renew else "No",
                     "status": t.status})
    cols = [_col("agreement", "Agreement"), _col("tenant", "Tenant"),
            _col("building", "Building"), _col("unit", "Unit"),
            _col("end", "Expires"), _col("days", "Days left", "number"),
            _col("notice_by", "Notice by"), _col("rent", "Monthly rent", "money"),
            _col("auto", "Auto-renew"), _col("status", "Status")]
    totals = {"rent": round(sum(r["rent"] for r in rows), 2)}
    note = "" if rows else (
        "No agreement expires between %s and %s. Widen the window to see the "
        "pipeline further out." % (frm, to))
    return _pack("renewals", cols, rows, totals, note)


def _deposits(frm, to, building=None):
    rows, covered_agreements = [], set()
    as_at = getdate(to)
    if frappe.db.exists("DocType", "Security Deposit"):
        deposits = frappe.get_all(
                "Security Deposit", filters={"docstatus": ["<", 2]},
                fields=["name", "tenancy_agreement", "tenant", "unit",
                        "amount", "status", "received_on", "deductions",
                        "refund_amount", "refunded_on"], limit=20000)
        agreement_names = list({d.tenancy_agreement for d in deposits
                                if d.tenancy_agreement})
        agreements = {
            a.name: a for a in frappe.get_all(
                "Tenancy Agreement",
                filters={"name": ["in", agreement_names]},
                fields=["name", "building", "unit"], limit=20000)
        } if agreement_names else {}
        unit_names = list({d.unit for d in deposits if d.unit})
        unit_buildings = {
            u.name: u.building for u in frappe.get_all(
                "Unit", filters={"name": ["in", unit_names]},
                fields=["name", "building"], limit=20000)
        } if unit_names else {}
        for d in deposits:
            if d.received_on and getdate(d.received_on) > as_at:
                continue
            agreement = agreements.get(d.tenancy_agreement)
            deposit_building = ((agreement and agreement.building)
                                or unit_buildings.get(d.unit))
            if building and deposit_building != building:
                continue
            if d.tenancy_agreement:
                covered_agreements.add(d.tenancy_agreement)
            settled_as_at = (d.status != "Held" and
                             (not d.refunded_on
                              or getdate(d.refunded_on) <= as_at))
            refunded = flt(d.refund_amount) if settled_as_at else 0.0
            deductions = flt(d.deductions) if settled_as_at else 0.0
            rows.append({"ref": d.name,
                         "tenant": frappe.db.get_value(
                             "Customer", d.tenant, "customer_name") or d.tenant,
                         "unit": "%s %s" % (
                             deposit_building or "", _unit_no(d.unit)),
                         "received": str(d.received_on or ""),
                         "status": (d.status if settled_as_at or d.status == "Held"
                                    else "Held as at date"),
                         "source": "Deposit record",
                         "original": round(flt(d.amount), 2),
                         "liability": (0.0 if settled_as_at else
                                       round(flt(d.amount), 2)),
                         "refunded": round(refunded, 2),
                         "deductions": round(deductions, 2)})

    # Historical agreements can state a deposit without having a Security
    # Deposit record. Merge those rows instead of hiding all of them as soon
    # as the first record-backed deposit exists.
    filters = {"docstatus": ["<", 2], "security_deposit": [">", 0],
               "status": ["in", ("Active", "Expiring", "Expired",
                                   "Terminated")]}
    if building:
        filters["building"] = building
    agreement_only = 0
    for t in frappe.get_all(
            "Tenancy Agreement", filters=filters,
            fields=["name", "tenant", "unit", "building",
                    "security_deposit", "status", "start_date"],
            limit=20000):
        if t.name in covered_agreements:
            continue
        if t.start_date and getdate(t.start_date) > as_at:
            continue
        amount = round(flt(t.security_deposit), 2)
        rows.append({"ref": t.name,
                     "tenant": frappe.db.get_value(
                         "Customer", t.tenant, "customer_name") or t.tenant,
                     "unit": "%s %s" % (t.building, _unit_no(t.unit)),
                     "received": str(t.start_date or ""),
                     "status": t.status, "source": "Agreement only",
                     "original": amount, "liability": amount,
                     "refunded": 0.0, "deductions": 0.0})
        agreement_only += 1

    cols = [_col("ref", "Reference"), _col("tenant", "Tenant"),
            _col("unit", "Unit"), _col("received", "Received"),
            _col("status", "Status"), _col("source", "Source"),
            _col("original", "Original deposit", "money"),
            _col("liability", "Liability", "money"),
            _col("refunded", "Refunded", "money"),
            _col("deductions", "Deductions", "money")]
    totals = {key: round(sum(r[key] for r in rows), 2)
              for key in ("original", "liability", "refunded", "deductions")}
    note = ("Point-in-time deposit position as at %s. A settled deposit has "
            "zero remaining liability because its settlement journal clears "
            "the full liability." % to)
    if agreement_only:
        note += (" %s agreement-only row%s show contractual deposits that "
                 "have no Security Deposit record; they are not confirmed "
                 "ledger balances." % (agreement_only,
                                        "" if agreement_only == 1 else "s"))
    if not rows:
        note = "No deposits are recorded, on agreements or as deposit records."
    return _pack("deposits", cols, rows, totals, note)


def _utilities(frm, to, building=None):
    rows = []
    if frappe.db.exists("DocType", "Utility Bill"):
        from darkbrown.api.utilities import _recovered

        filters = {"docstatus": ["<", 2], "status": ["!=", "Cancelled"],
                   "period_end": ["between", [frm, to]]}
        if building:
            filters["building"] = building
        bills = frappe.get_all(
                "Utility Bill", filters=filters,
                fields=["name", "building", "utility_type", "amount"],
                limit=20000)
        allocated_by_bill, recovered_by_bill = _recovered(bills)
        agg = defaultdict(lambda: {"billed": 0.0, "allocated": 0.0,
                                   "recovered": 0.0, "n": 0})
        for u in bills:
            a = agg[(u.building, u.utility_type)]
            a["billed"] += flt(u.amount)
            a["allocated"] += flt(allocated_by_bill.get(u.name))
            a["recovered"] += flt(recovered_by_bill.get(u.name))
            a["n"] += 1
        for (b, kind), a in sorted(agg.items()):
            rows.append({"building": b, "kind": kind, "bills": a["n"],
                         "billed": round(a["billed"], 2),
                         "allocated": round(a["allocated"], 2),
                         "recovered": round(a["recovered"], 2),
                         "unrecovered": round(a["billed"] - a["recovered"], 2),
                         "pct": round(a["recovered"] / a["billed"] * 100, 1)
                         if a["billed"] else None})
    cols = [_col("building", "Building"), _col("kind", "Utility"),
            _col("bills", "Bills", "number"),
            _col("billed", "Billed", "money"),
            _col("allocated", "Allocated", "money"),
            _col("recovered", "Recovered", "money"),
            _col("unrecovered", "Unrecovered", "money"),
            _col("pct", "Recovery", "percent")]
    billed = sum(r["billed"] for r in rows)
    allocated = sum(r["allocated"] for r in rows)
    rec = sum(r["recovered"] for r in rows)
    totals = {"bills": sum(r["bills"] for r in rows),
              "billed": round(billed, 2),
              "allocated": round(allocated, 2),
              "recovered": round(rec, 2),
              "unrecovered": round(billed - rec, 2),
              "pct": round(rec / billed * 100, 1) if billed else None}
    note = ("Recovered means an allocation linked to a Sales Invoice; "
            "allocated but uninvoiced amounts remain unrecovered.") if rows else (
        "No utility bills recorded in this window. The pack fills as bills are "
        "entered against meters.")
    return _pack("utilities", cols, rows, totals, note)


def _audit(frm, to, building=None):
    """Frappe writes a Version row for every change to a tracked doctype. That
    is the audit trail; nothing here needed inventing, only reading."""
    watched = ("Tenancy Agreement", "Head Lease", "Sales Invoice",
               "Purchase Invoice", "Payment Entry", "Cheque", "Unit",
               "Building", "Journal Entry")
    rows = []
    for v in frappe.get_all(
            "Version",
            filters={"ref_doctype": ["in", watched],
                     "creation": ["between", [frm, str(getdate(to)) + " 23:59:59"]]},
            fields=["ref_doctype", "docname", "owner", "creation", "data"],
            order_by="creation desc", limit=1000):
        try:
            changed = frappe.parse_json(v.data or "{}").get("changed") or []
        except Exception:
            changed = []
        fields = ", ".join(str(c[0]) for c in changed[:6]) if changed else ""
        rows.append({"when": str(v.creation)[:19], "doctype": v.ref_doctype,
                     "record": v.docname, "user": v.owner,
                     "fields": fields, "changes": len(changed)})
    cols = [_col("when", "When"), _col("doctype", "Record type"),
            _col("record", "Record"), _col("user", "User"),
            _col("fields", "Fields changed"),
            _col("changes", "Count", "number")]
    note = "" if rows else (
        "No tracked changes in this window. Frappe records a version only when "
        "a document is edited after submission, so a clean load produces none.")
    if len(rows) == 1000:
        note = "Showing the most recent 1,000 changes. Narrow the window."
    return _pack("audit", cols, rows, {}, note)


BUILDERS = {
    "pl_by_building": _pl_by_building, "spread": _spread, "arrears": _arrears,
    "cheques": _cheques, "occupancy": _occupancy, "renewals": _renewals,
    "deposits": _deposits, "utilities": _utilities, "audit": _audit,
}


# ----------------------------------------------------------------- endpoints

@frappe.whitelist()
def catalogue():
    """The nine packs, with the buildings a scope filter can offer."""
    guard(MD, GM, ACC)
    return {
        "packs": [{"key": k, "title": t, "description": d, "source": s}
                  for k, t, d, s in CATALOGUE],
        "buildings": frappe.get_all("Building", pluck="name", order_by="name"),
        "default_from": str(getdate(today()).replace(day=1)),
        "default_to": str(today()),
    }


@frappe.whitelist()
def run(key, frm=None, to=None, building=None):
    """One pack, over one window, optionally for one building."""
    guard(MD, GM, ACC)
    if key not in BUILDERS:
        frappe.throw("Unknown report %r." % key)
    frm, to = _window(frm, to)
    if getdate(frm) > getdate(to):
        frappe.throw("The From date is after the To date.")
    out = BUILDERS[key](frm, to, building or None)
    out["from"] = frm
    out["to"] = to
    out["building"] = building or ""
    out["generated"] = str(frappe.utils.now())
    return out
