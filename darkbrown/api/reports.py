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
     "Sales Invoices and Head Lease records"),
    ("arrears", "Arrears ageing",
     "0-30 / 31-60 / 61-90 / 90+ with tenant and unit detail",
     "Unpaid Sales Invoices"),
    ("cheques", "Cheque register",
     "Every cheque by status, bank and maturity",
     "Cheque records"),
    ("occupancy", "Occupancy and voids",
     "Occupied, vacant, void days and the rent those voids cost",
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

    rows_by = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    gl = frappe.get_all(
        "GL Entry",
        filters={"is_cancelled": 0, "company": company,
                 "posting_date": ["between", [frm, to]]},
        fields=["account", "cost_center", "debit", "credit", "posting_date"],
        limit=50000)
    roots = {a.name: a.root_type for a in frappe.get_all(
        "Account", filters={"company": company},
        fields=["name", "root_type"])}

    for e in gl:
        b = cost_centres.get(e.cost_center)
        if not b:
            continue
        root = roots.get(e.account)
        month = str(getdate(e.posting_date).replace(day=1))
        if root == "Income":
            rows_by[(b, month)]["income"] += flt(e.credit) - flt(e.debit)
        elif root == "Expense":
            rows_by[(b, month)]["expense"] += flt(e.debit) - flt(e.credit)

    rows = []
    for (b, month), v in sorted(rows_by.items()):
        net = v["income"] - v["expense"]
        rows.append({"building": b, "month": month[:7],
                     "income": round(v["income"], 2),
                     "expense": round(v["expense"], 2),
                     "net": round(net, 2),
                     "margin": round(net / v["income"] * 100, 1)
                     if v["income"] else None})

    cols = [_col("building", "Building"), _col("month", "Month"),
            _col("income", "Revenue", "money"),
            _col("expense", "Head-lease cost", "money"),
            _col("net", "Net", "money"), _col("margin", "Margin", "percent")]
    inc = sum(r["income"] for r in rows)
    exp = sum(r["expense"] for r in rows)
    totals = {"income": round(inc, 2), "expense": round(exp, 2),
              "net": round(inc - exp, 2),
              "margin": round((inc - exp) / inc * 100, 1) if inc else None}
    note = ""
    if not rows:
        note = ("Nothing posted against a building cost centre in this window. "
                "A posting with no cost centre cannot be attributed to a "
                "building and is left out rather than spread across them.")
    elif not any(r["expense"] for r in rows):
        note = ("No head-lease cost is posted in this window, so every margin "
                "reads 100%. Revenue without its cost is not a margin.")
    return _pack("pl_by_building", cols, rows, totals, note)


def _spread(frm, to, building=None):
    company = _company()
    months = _months(frm, to)
    leases = frappe.get_all(
        "Head Lease",
        filters={"status": ["in", ("Active", "Expiring", "Expired")]},
        fields=["building", "annual_rent", "start_date", "end_date"])

    billed = defaultdict(float)
    for si in frappe.get_all(
            "Sales Invoice", filters={"docstatus": 1, "company": company,
                                      "posting_date": ["between", [frm, to]]},
            fields=["name", "grand_total", "cost_center"], limit=20000):
        billed[si.cost_center] += flt(si.grand_total)
    posted_cost = defaultdict(float)
    for pi in frappe.get_all(
            "Purchase Invoice", filters={"docstatus": 1, "company": company,
                                         "posting_date": ["between", [frm, to]]},
            fields=["grand_total", "cost_center"], limit=20000):
        posted_cost[pi.cost_center] += flt(pi.grand_total)
    by_cc = {b.cost_center: b.name for b in frappe.get_all(
        "Building", fields=["name", "cost_center"]) if b.cost_center}

    rows = []
    for b in sorted({x.building for x in leases} | set(by_cc.values())):
        if building and b != building:
            continue
        rent = sum(v for cc, v in billed.items() if by_cc.get(cc) == b)
        cost = 0.0
        for lease in [x for x in leases if x.building == b]:
            monthly = flt(lease.annual_rent) / 12.0
            for m in months:
                if getdate(lease.start_date) <= get_last_day(m) and \
                        getdate(lease.end_date) >= m:
                    cost += monthly
        posted = sum(v for cc, v in posted_cost.items() if by_cc.get(cc) == b)
        units = frappe.db.count("Unit", {"building": b})
        rows.append({"building": b, "units": units,
                     "rent": round(rent, 2), "cost": round(posted, 2),
                     "spread": round(rent - posted, 2),
                     "margin": round((rent - posted) / rent * 100, 1)
                     if rent else None,
                     "accrued": round(cost, 2),
                     "gap": round(cost - posted, 2),
                     "per_unit": round((rent - posted) / units, 2)
                     if units else None})

    cols = [_col("building", "Building"), _col("units", "Units", "number"),
            _col("rent", "Sublease revenue", "money"),
            _col("cost", "Head-lease cost", "money"),
            _col("spread", "Spread", "money"),
            _col("margin", "Margin", "percent"),
            _col("accrued", "Cost accrued", "money"),
            _col("gap", "Not yet posted", "money"),
            _col("per_unit", "Spread per unit", "money")]
    rent = sum(r["rent"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    accrued = sum(r["accrued"] for r in rows)
    totals = {"units": sum(r["units"] for r in rows),
              "rent": round(rent, 2), "cost": round(cost, 2),
              "spread": round(rent - cost, 2),
              "margin": round((rent - cost) / rent * 100, 1) if rent else None,
              "accrued": round(accrued, 2), "gap": round(accrued - cost, 2)}
    gap = round(accrued - cost, 2)
    note = ("Spread and margin use the cost actually posted, so this pack and "
            "the P&L cannot disagree. Cost accrued is what the head leases say "
            "is owed across the window; the gap between them is rent that has "
            "not been invoiced by the landlord yet.")
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
    rows = []
    for si in frappe.get_all(
            "Sales Invoice",
            filters={"docstatus": 1, "outstanding_amount": [">", 0],
                     "posting_date": ["<=", str(as_on)]},
            fields=["name", "customer", "posting_date", "due_date",
                    "outstanding_amount", "grand_total", "cost_center",
                    "remarks"], limit=20000):
        due = getdate(si.due_date or si.posting_date)
        age = (as_on - due).days
        bucket = ("current" if age <= 0 else "b30" if age <= 30
                  else "b60" if age <= 60 else "b90" if age <= 90 else "b90p")
        # The loader writes "... | AK-12 G-01B | ..." into remarks. Matching a
        # real building name is exact; guessing at the shape of the segment is
        # not, and would mislabel every invoice from a differently named one.
        unit = ""
        for part in (si.remarks or "").split("|"):
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
    note = "" if rows else "Nothing is outstanding as at %s." % as_on
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
        rows.append({"cheque": c.name, "direction": c.direction,
                     "party": c.party, "bank": c.bank, "no": c.cheque_no,
                     "date": str(c.cheque_date), "building": c.building,
                     "unit": c.unit, "status": c.status,
                     "amount": round(flt(c.amount), 2)})
    cols = [_col("cheque", "Ref"), _col("direction", "Direction"),
            _col("party", "Party"), _col("bank", "Bank"), _col("no", "No"),
            _col("date", "Maturity"), _col("building", "Building"),
            _col("unit", "Unit"), _col("status", "Status"),
            _col("amount", "Amount", "money")]
    totals = {"amount": round(sum(r["amount"] for r in rows), 2)}
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
                            filters={"docstatus": ["<", 2]},
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
        rows.append({"building": u.building, "unit": u.unit_no,
                     "type": u.unit_type or "", "status": u.status,
                     "occupied": occupied_days, "void": void_days,
                     "pct": round(occupied_days / span * 100, 1)
                     if span else None,
                     "rent": round(rent, 2),
                     "lost": round(void_days / 30.0 * flt(u.asking_rent or rent), 2)})
    cols = [_col("building", "Building"), _col("unit", "Unit"),
            _col("type", "Type"), _col("status", "Status"),
            _col("occupied", "Occupied days", "number"),
            _col("void", "Void days", "number"),
            _col("pct", "Occupancy", "percent"),
            _col("rent", "Current rent", "money"),
            _col("lost", "Rent lost to voids", "money")]
    occ = sum(r["occupied"] for r in rows)
    tot = span * len(rows)
    totals = {"occupied": occ, "void": sum(r["void"] for r in rows),
              "pct": round(occ / tot * 100, 1) if tot else None,
              "rent": round(sum(r["rent"] for r in rows), 2),
              "lost": round(sum(r["lost"] for r in rows), 2)}
    return _pack("occupancy", cols, rows, totals,
                 "Rent lost to voids values a void month at the unit's asking "
                 "rent, falling back to its current rent where no asking rent "
                 "is set. It is an opportunity figure, not a ledger one.")


def _renewals(frm, to, building=None):
    filters = {"docstatus": ["<", 2], "end_date": ["between", [frm, to]]}
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
    rows = []
    if frappe.db.exists("DocType", "Security Deposit"):
        for d in frappe.get_all(
                "Security Deposit", filters={"docstatus": ["<", 2]},
                fields=["name", "tenant", "unit", "amount", "status",
                        "received_on", "refund_amount", "refunded_on"],
                limit=20000):
            rows.append({"ref": d.name,
                         "tenant": frappe.db.get_value(
                             "Customer", d.tenant, "customer_name") or d.tenant,
                         "unit": d.unit, "held": round(flt(d.amount), 2),
                         "received": str(d.received_on or ""),
                         "status": d.status,
                         "refunded": round(flt(d.refund_amount), 2)})
    note = ""
    if not rows:
        # Fall back to what the agreements say they hold, which is the only
        # record of a deposit until the deposit module is used.
        filters = {"docstatus": ["<", 2], "security_deposit": [">", 0]}
        if building:
            filters["building"] = building
        for t in frappe.get_all(
                "Tenancy Agreement", filters=filters,
                fields=["name", "tenant", "unit", "building",
                        "security_deposit", "status", "start_date"],
                limit=20000):
            rows.append({"ref": t.name,
                         "tenant": frappe.db.get_value(
                             "Customer", t.tenant, "customer_name") or t.tenant,
                         "unit": "%s %s" % (t.building, _unit_no(t.unit)),
                         "held": round(flt(t.security_deposit), 2),
                         "received": str(t.start_date or ""),
                         "status": t.status, "refunded": 0.0})
        if rows:
            note = ("No Security Deposit records exist, so this reads the "
                    "deposit stated on each tenancy agreement. It is what the "
                    "contracts say is held, not a ledger balance - deposits "
                    "are not posted to the ledger by the historical load.")
    cols = [_col("ref", "Reference"), _col("tenant", "Tenant"),
            _col("unit", "Unit"), _col("received", "Received"),
            _col("status", "Status"), _col("held", "Held", "money"),
            _col("refunded", "Refunded", "money")]
    totals = {"held": round(sum(r["held"] for r in rows), 2),
              "refunded": round(sum(r["refunded"] for r in rows), 2)}
    if not rows:
        note = "No deposits are recorded, on agreements or as deposit records."
    return _pack("deposits", cols, rows, totals, note)


def _utilities(frm, to, building=None):
    rows = []
    if frappe.db.exists("DocType", "Utility Bill"):
        filters = {"docstatus": ["<", 2],
                   "period_start": ["between", [frm, to]]}
        if building:
            filters["building"] = building
        agg = defaultdict(lambda: {"billed": 0.0, "recovered": 0.0, "n": 0})
        for u in frappe.get_all(
                "Utility Bill", filters=filters,
                fields=["building", "utility_type", "amount",
                        "allocated_total"], limit=20000):
            a = agg[(u.building, u.utility_type)]
            a["billed"] += flt(u.amount)
            a["recovered"] += flt(u.allocated_total)
            a["n"] += 1
        for (b, kind), a in sorted(agg.items()):
            rows.append({"building": b, "kind": kind, "bills": a["n"],
                         "billed": round(a["billed"], 2),
                         "recovered": round(a["recovered"], 2),
                         "shortfall": round(a["billed"] - a["recovered"], 2),
                         "pct": round(a["recovered"] / a["billed"] * 100, 1)
                         if a["billed"] else None})
    cols = [_col("building", "Building"), _col("kind", "Utility"),
            _col("bills", "Bills", "number"),
            _col("billed", "Billed", "money"),
            _col("recovered", "Recovered", "money"),
            _col("shortfall", "Shortfall", "money"),
            _col("pct", "Recovery", "percent")]
    billed = sum(r["billed"] for r in rows)
    rec = sum(r["recovered"] for r in rows)
    totals = {"bills": sum(r["bills"] for r in rows),
              "billed": round(billed, 2), "recovered": round(rec, 2),
              "shortfall": round(billed - rec, 2),
              "pct": round(rec / billed * 100, 1) if billed else None}
    note = "" if rows else (
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
