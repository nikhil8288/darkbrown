"""Utilities: what the provider billed us against what we recovered.

The Utility Bill, Utility Bill Allocation and Utility Meter doctypes have been
on the site since the first migrate. Nothing ever read them. The Utilities
screen multiplied a building's unit count by a fixed figure and printed the
result next to real portfolio data, which is the worst of both — it looks like
a measurement and it is arithmetic on a constant.

Recovery here means one thing only: an allocation line that carries a Sales
Invoice. An allocation without an invoice is a share that was worked out and
never billed, and that is exactly the number this screen exists to show.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today, add_months
from darkbrown.guards import guard, ACC, GM, MD, MNT
from darkbrown.permissions import require_building_access, require_file_access

#: How far back the screen reads. Long enough to see a variance develop.
MONTHS = 6

#: A building whose billing jumps by more than this against its own trailing
#: average is flagged. It is a prompt to look, not a finding.
VARIANCE = 0.25


def _period(months=None):
    end = getdate(today())
    return str(getdate(add_months(end, -(months or MONTHS)))), str(end)


def _bill_rows(frm, to):
    return frappe.get_all(
        "Utility Bill",
        filters={"status": ["!=", "Cancelled"],
                 "period_end": ["between", [frm, to]]},
        fields=["name", "building", "utility_type", "bill_no", "status",
                "period_start", "period_end", "amount", "consumption",
                "allocated_total", "unallocated", "allocation_basis"],
        order_by="period_end desc", limit=1000)


def _recovered(bills):
    """Allocation value that actually reached an invoice, per bill."""
    if not bills:
        return {}, {}
    rows = frappe.get_all(
        "Utility Bill Allocation",
        filters={"parent": ["in", [b.name for b in bills]]},
        fields=["parent", "amount", "sales_invoice", "unit", "tenant"],
        limit=20000)
    billed_out, invoiced = {}, {}
    for r in rows:
        billed_out[r.parent] = billed_out.get(r.parent, 0.0) + flt(r.amount)
        if r.sales_invoice:
            invoiced[r.parent] = invoiced.get(r.parent, 0.0) + flt(r.amount)
    return billed_out, invoiced


def _live_tenancies(building, on_date):
    rows = frappe.get_all(
        "Tenancy Agreement",
        filters={"building": building,
                 "status": ["in", ("Active", "Expiring")]},
        fields=["name", "tenant", "unit", "start_date", "end_date"],
        order_by="unit asc")
    on_date = getdate(on_date)
    return [r for r in rows
            if r.unit and r.tenant
            and (not r.start_date or getdate(r.start_date) <= on_date)
            and (not r.end_date or getdate(r.end_date) >= on_date)]


def _weighted_allocations(data, tenancies, amount):
    """Return auditable allocation rows without trusting client party data."""
    basis = data.get("allocation_basis") or "Equal Split"
    by_unit = {r.unit: r for r in tenancies}
    supplied = data.get("allocations") or []
    if basis == "Manual":
        seen, out = set(), []
        for item in supplied:
            unit = item.get("unit")
            if unit in seen:
                frappe.throw(_("Unit {0} is listed twice.").format(unit))
            seen.add(unit)
            tenancy = by_unit.get(unit)
            if not tenancy:
                frappe.throw(_(
                    "{0} has no live tenancy in this building for the bill period."
                ).format(unit or "An allocation"))
            value = flt(item.get("amount"), 2)
            if value <= 0:
                frappe.throw(_("Every manual allocation needs a positive amount."))
            out.append({"unit": unit, "tenant": tenancy.tenant,
                        "amount": value, "consumption": flt(
                            item.get("consumption"), 3)})
        if not out:
            frappe.throw(_("A manual allocation needs at least one unit."))
    else:
        if not tenancies:
            frappe.throw(_(
                "This building has no live tenancies for the bill period."))
        if basis == "Equal Split":
            weights = {r.unit: 1.0 for r in tenancies}
        elif basis == "Area":
            weights = {r.unit: flt(frappe.db.get_value(
                "Unit", r.unit, "area_sqm")) for r in tenancies}
            if any(v <= 0 for v in weights.values()):
                frappe.throw(_(
                    "Every occupied unit needs an area before an area allocation."))
        elif basis == "Sub-Meter":
            readings = {x.get("unit"): flt(x.get("consumption"), 3)
                        for x in supplied}
            weights = {r.unit: readings.get(r.unit, 0.0) for r in tenancies}
            if any(v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
                frappe.throw(_(
                    "Sub-meter allocation needs non-negative readings and a positive total."))
        else:
            frappe.throw(_("Unsupported utility allocation basis: {0}.").format(basis))

        total_weight = sum(weights.values())
        out, used = [], 0.0
        for i, tenancy in enumerate(tenancies):
            value = (round(amount - used, 2) if i == len(tenancies) - 1
                     else round(amount * weights[tenancy.unit] / total_weight, 2))
            used += value
            out.append({"unit": tenancy.unit, "tenant": tenancy.tenant,
                        "amount": value,
                        "consumption": (weights[tenancy.unit]
                                        if basis == "Sub-Meter" else 0.0)})

    allocated = round(sum(x["amount"] for x in out), 2)
    if allocated > amount + 0.005:
        frappe.throw(_("Allocations exceed the bill amount."))
    for row in out:
        row["share_pct"] = round(
            row["amount"] / allocated * 100, 4) if allocated else 0
    return out


@frappe.whitelist()
def record_bill(payload):
    """Capture a provider bill and its tenant recovery allocation.

    The bill itself does not touch the ledger. Allocations are queued into the
    next governed invoice run and become recoveries only after that run is
    approved and its Sales Invoices are submitted.
    """
    guard(MD, GM, ACC)
    data = frappe.parse_json(payload)
    building = data.get("building")
    require_building_access(building)
    if not building or not frappe.db.exists("Building", building):
        frappe.throw(_("Choose an existing building."))

    utility_type = data.get("utility_type") or "Kahramaa"
    if utility_type not in ("Kahramaa", "Water", "Gas"):
        frappe.throw(_("Unsupported utility type."))
    bill_no = str(data.get("bill_no") or "").strip()
    if not bill_no:
        frappe.throw(_("A utility bill needs the provider bill number."))
    if frappe.db.exists("Utility Bill", {
            "building": building, "utility_type": utility_type,
            "bill_no": bill_no, "status": ["!=", "Cancelled"]}):
        frappe.throw(_("That provider bill is already on the register."))

    if not data.get("period_start") or not data.get("period_end"):
        frappe.throw(_("A utility bill needs both period dates."))
    period_start, period_end = (getdate(data.get("period_start")),
                                getdate(data.get("period_end")))
    if period_start > period_end:
        frappe.throw(_("The utility period cannot end before it starts."))
    if period_end > getdate(today()):
        frappe.throw(_("A utility bill period cannot end in the future."))
    amount = flt(data.get("amount"), 2)
    if amount <= 0:
        frappe.throw(_("A utility bill amount must be greater than zero."))

    bill_scan = data.get("bill_scan")
    if bill_scan:
        require_file_access(bill_scan)
    basis = data.get("allocation_basis") or "Equal Split"
    tenancies = _live_tenancies(building, period_end)
    allocations = _weighted_allocations(data, tenancies, amount)
    company = (frappe.db.get_single_value("DBR Settings", "default_company")
               or frappe.db.get_value("Company", {}, "name"))
    doc = frappe.get_doc({
        "doctype": "Utility Bill", "building": building,
        "utility_type": utility_type, "status": "Allocated",
        "company": company, "bill_no": bill_no,
        "period_start": period_start, "period_end": period_end,
        "amount": amount, "consumption": flt(data.get("consumption"), 3),
        "bill_scan": bill_scan, "allocation_basis": basis,
    })
    for row in allocations:
        doc.append("allocations", row)
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return {"bill": doc.name, "status": doc.status,
            "allocated": round(sum(x["amount"] for x in allocations), 2),
            "unallocated": round(amount - sum(x["amount"] for x in allocations), 2),
            "tenants": len(allocations)}


@frappe.whitelist()
def overview(months=None):
    """Per-building billed, allocated and recovered over the window.

    Returns an empty list rather than zeroes when no bill has ever been
    entered — a portfolio with no utility bills on it is a real state, and
    the screen says so instead of showing five noughts as if it had looked.
    """
    guard(MD, GM, ACC, MNT)
    frm, to = _period(months)
    bills = _bill_rows(frm, to)
    if not bills:
        return {"rows": [], "from": frm, "to": to, "bills": 0,
                "billed": 0, "allocated": 0, "recovered": 0, "unrecovered": 0,
                "flagged": 0}

    allocated_by_bill, invoiced_by_bill = _recovered(bills)
    names = {b: (frappe.db.get_value("Building", b, "building_name") or b)
             for b in {x.building for x in bills if x.building}}

    per = {}
    months_seen = {}
    for b in bills:
        key = b.building or "—"
        row = per.setdefault(key, {
            "id": key, "n": names.get(key, key), "bills": 0,
            "billed": 0.0, "allocated": 0.0, "recovered": 0.0,
            "disputed": 0, "unallocated": 0.0})
        row["bills"] += 1
        row["billed"] += flt(b.amount)
        row["allocated"] += allocated_by_bill.get(b.name, flt(b.allocated_total))
        row["recovered"] += invoiced_by_bill.get(b.name, 0.0)
        row["unallocated"] += flt(b.unallocated)
        if b.status == "Disputed":
            row["disputed"] += 1
        months_seen.setdefault(key, {})
        m = str(b.period_end)[:7]
        months_seen[key][m] = months_seen[key].get(m, 0.0) + flt(b.amount)

    rows = []
    for key, row in per.items():
        # Variance is a building against its own trailing average, not against
        # the portfolio — buildings differ too much for a shared baseline.
        series = sorted(months_seen.get(key, {}).items())
        flagged, why = False, ""
        if len(series) >= 3:
            latest = series[-1][1]
            prior = [v for _, v in series[:-1]]
            avg = sum(prior) / len(prior)
            if avg > 0 and (latest - avg) / avg > VARIANCE:
                flagged = True
                why = "%+d%% against its own trailing average" % round(
                    (latest - avg) / avg * 100)
        billed = row["billed"]
        row["rate"] = round(row["recovered"] / billed * 100) if billed else 0
        row["unrecovered"] = round(billed - row["recovered"], 2)
        row["flagged"] = flagged
        row["why"] = why or ("disputed bill on this building"
                             if row["disputed"] else "")
        for k in ("billed", "allocated", "recovered", "unallocated"):
            row[k] = round(row[k], 2)
        rows.append(row)
    rows.sort(key=lambda r: -r["unrecovered"])

    billed = round(sum(r["billed"] for r in rows), 2)
    recovered = round(sum(r["recovered"] for r in rows), 2)
    return {
        "rows": rows, "from": frm, "to": to, "bills": len(bills),
        "billed": billed, "allocated": round(
            sum(r["allocated"] for r in rows), 2),
        "recovered": recovered, "unrecovered": round(billed - recovered, 2),
        "rate": round(recovered / billed * 100) if billed else 0,
        "flagged": sum(1 for r in rows if r["flagged"]),
    }


@frappe.whitelist()
def bills(building=None, months=None):
    """The bills themselves, for the building workspace and for drilling in."""
    guard(MD, GM, ACC, MNT)
    frm, to = _period(months)
    rows = _bill_rows(frm, to)
    if building:
        rows = [r for r in rows if r.building == building]
    allocated_by_bill, invoiced_by_bill = _recovered(rows)
    out = []
    for b in rows:
        billed = flt(b.amount)
        rec = invoiced_by_bill.get(b.name, 0.0)
        out.append({
            "id": b.name, "b": b.building or "—",
            "ty": b.utility_type or "Kahramaa",
            "no": b.bill_no or "—", "st": b.status or "Draft",
            "from": str(b.period_start or ""), "to": str(b.period_end or ""),
            "amt": round(billed, 2),
            "alloc": round(allocated_by_bill.get(
                b.name, flt(b.allocated_total)), 2),
            "rec": round(rec, 2),
            "open": round(billed - rec, 2),
            "basis": b.allocation_basis or "—",
            "cons": flt(b.consumption),
        })
    return out


@frappe.whitelist()
def meters(building=None):
    """Meters on a building, so an unmetered unit is visible as one."""
    guard(MD, GM, ACC, MNT)
    filters = {}
    if building:
        filters["building"] = building
    rows = frappe.get_all(
        "Utility Meter", filters=filters,
        fields=["name", "building", "unit", "meter_type", "meter_no",
                "account_no", "status"],
        order_by="building asc, unit asc", limit=2000)
    return [{"id": r.name, "b": r.building or "—", "u": r.unit or "building",
             "ty": r.meter_type or "Kahramaa", "no": r.meter_no or "—",
             "acct": r.account_no or "—", "st": r.status or "Active"}
            for r in rows]
