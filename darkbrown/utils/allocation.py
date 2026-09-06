"""Spreading the company's common cost over the buildings that were carrying it.

An audit fee is not a building's cost in the ledger and never should be - it
posts to the overhead cost centre and stays there, so the books say what
actually happened. But a building's margin that ignores overhead flatters
every building, and the arbitrage spread is the number this business is run
on. So the cost is divided here, in the reporting layer, and the ledger is
left alone.

Three decisions, each of which changes the answer:

    The split is weighted by head-lease cost, not spread evenly. Twenty-three
    buildings ranging from four units to forty do not consume the same share
    of a salary bill, and an even split would charge the smallest building the
    same as the largest - making its margin a property of the rule rather than
    of its lease.

    A building shares in a month only if it was live in that month. Live means
    Active or on Notice Period, and - where the dates are recorded - handed
    over before the month ended and not exited before it began. A building
    that opened in May does not carry March's salary.

    Every share is a whole riyal, and the shares add back to the total exactly.
    Rounding each share independently leaves a few riyals in nobody's column,
    which is how a reconciliation starts failing for no reason anyone can find.
    The largest-remainder method rounds everything down, then gives the
    leftover riyals one at a time to whichever buildings were rounded down
    hardest.

Nothing here writes. It reads the ledger and returns numbers.
"""

from collections import defaultdict

import frappe
from frappe.utils import (add_months, flt, get_first_day, get_last_day,
                          getdate, today)

from darkbrown.utils.chart_of_accounts import OVERHEAD_COST_CENTER

#: Building states that carry a share of overhead.
LIVE_STATES = ("Active", "Notice Period")


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or (frappe.get_all("Company", limit=1) or [{}])[0].get("name"))


def overhead_cost_center(company=None):
    company = company or _company()
    return frappe.db.get_value(
        "Cost Center", {"cost_center_name": OVERHEAD_COST_CENTER,
                        "company": company}, "name")


# ----------------------------------------------------------------- the weights

def live_buildings(month_start, month_end):
    """Buildings sharing overhead in one month, with their head-lease cost.

    Returns a list of dicts: building, cost_center, weight.

    The weight is the monthly head-lease rent on the lease that covered the
    month. Where a building has no lease covering it - which happens while a
    renewal is mid-signature - the most recent lease on that building is used
    rather than dropping the building out of the split, because a building
    that is live is consuming overhead whether or not its paperwork is filed.
    """
    buildings = frappe.get_all(
        "Building",
        filters={"status": ["in", LIVE_STATES]},
        fields=["name", "cost_center", "handover_date", "exit_date"])

    leases = defaultdict(list)
    for hl in frappe.get_all(
            "Head Lease",
            filters={"docstatus": ["<", 2]},
            fields=["building", "monthly_rent", "start_date", "end_date"]):
        leases[hl.building].append(hl)

    out = []
    for b in buildings:
        if b.handover_date and getdate(b.handover_date) > getdate(month_end):
            continue
        if b.exit_date and getdate(b.exit_date) < getdate(month_start):
            continue

        mine = leases.get(b.name) or []
        covering = [h for h in mine
                    if h.start_date and getdate(h.start_date) <= getdate(month_end)
                    and (not h.end_date or getdate(h.end_date) >= getdate(month_start))]
        pool = covering or mine
        weight = max((flt(h.monthly_rent) for h in pool), default=0.0)
        out.append({"building": b.name, "cost_center": b.cost_center,
                    "weight": weight})
    return out


# -------------------------------------------------------------- the arithmetic

def split(total, weights):
    """Divide `total` across `weights` in whole units, summing back exactly.

    `weights` is a dict of key -> weight. Returns key -> integer amount.

    Where every weight is zero the split is even, because the alternative is
    returning nothing at all and quietly losing the cost. Where there are no
    keys at all, nothing is returned and the caller keeps the residue.
    """
    keys = list(weights.keys())
    if not keys:
        return {}

    total = flt(total)
    sign = -1 if total < 0 else 1
    amount = abs(total)

    base = {k: flt(weights[k]) for k in keys}
    denom = sum(base.values())
    if denom <= 0:
        base = {k: 1.0 for k in keys}
        denom = float(len(keys))

    exact = {k: amount * base[k] / denom for k in keys}
    floors = {k: int(exact[k]) for k in keys}
    left = int(round(amount)) - sum(floors.values())

    # Biggest fractional part first; ties broken on the key so the same inputs
    # always produce the same output.
    order = sorted(keys, key=lambda k: (-(exact[k] - floors[k]), str(k)))
    i = 0
    while left > 0 and order:
        floors[order[i % len(order)]] += 1
        left -= 1
        i += 1
    while left < 0 and order:
        k = order[i % len(order)]
        if floors[k] > 0:
            floors[k] -= 1
            left += 1
        i += 1

    return {k: sign * v for k, v in floors.items()}


# ------------------------------------------------------------------ the pool

def _months(frm, to):
    """Every month the window touches, as (start, end) pairs."""
    cur = get_first_day(getdate(frm))
    last = get_first_day(getdate(to))
    out = []
    while cur <= last:
        out.append((cur, get_last_day(cur)))
        cur = get_first_day(add_months(cur, 1))
    return out


def overhead_pool(frm, to, company=None):
    """Common cost sitting on the overhead centre, by month and by account."""
    company = company or _company()
    cc = overhead_cost_center(company)
    if not cc:
        return {}

    rows = frappe.get_all(
        "GL Entry",
        filters={"is_cancelled": 0, "cost_center": cc,
                 "posting_date": ["between", [getdate(frm), getdate(to)]]},
        fields=["account", "posting_date", "debit", "credit"],
        limit=50000)
    if not rows:
        return {}

    expense = {a.name for a in frappe.get_all(
        "Account", filters={"company": company, "root_type": "Expense"},
        fields=["name"])}

    pool = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r.account not in expense:
            continue
        month = str(get_first_day(getdate(r.posting_date)))
        pool[month][r.account] += flt(r.debit) - flt(r.credit)
    return {m: dict(v) for m, v in pool.items()}


def allocate(frm=None, to=None, company=None):
    """Overhead spread over the buildings that were live, month by month.

    Returns:
        by_building        building -> total allocated over the window
        by_building_month  (building, "YYYY-MM") -> allocated
        by_account         account -> total in the pool
        unallocated        cost in months where no building was live
        total              the pool
        months             what each month split, and across how many
    """
    to = getdate(to or today())
    frm = getdate(frm or add_months(to, -12))
    company = company or _company()

    pool = overhead_pool(frm, to, company)
    by_building = defaultdict(float)
    by_building_month = defaultdict(float)
    by_account = defaultdict(float)
    months, unallocated, total = [], 0.0, 0.0

    for month_start, month_end in _months(frm, to):
        key = str(month_start)
        accounts = pool.get(key) or {}
        month_total = sum(accounts.values())
        for acc, amt in accounts.items():
            by_account[acc] += amt
        total += month_total
        if not month_total:
            continue

        live = live_buildings(month_start, month_end)
        if not live:
            unallocated += month_total
            months.append({"month": key[:7], "amount": round(month_total, 2),
                           "buildings": 0, "allocated": 0.0})
            continue

        weights = {b["building"]: b["weight"] for b in live}
        shares = split(month_total, weights)
        for building, amount in shares.items():
            by_building[building] += amount
            by_building_month[(building, key[:7])] += amount
        months.append({"month": key[:7], "amount": round(month_total, 2),
                       "buildings": len(live),
                       "allocated": float(sum(shares.values()))})

    return {
        "by_building": {k: float(v) for k, v in by_building.items()},
        "by_building_month": {"%s|%s" % k: float(v)
                              for k, v in by_building_month.items()},
        "by_account": {k: round(v, 2) for k, v in by_account.items()},
        "unallocated": round(unallocated, 2),
        "total": round(total, 2),
        "months": months,
        "frm": str(frm), "to": str(to),
        "basis": "Head-lease cost, whole riyals, largest remainder",
    }


@frappe.whitelist()
def preview(frm=None, to=None):
    """What the split would look like, for the screen that explains it."""
    from darkbrown.guards import guard, ACC, GM, MD
    guard(MD, GM, ACC)
    out = allocate(frm, to)
    names = {b.name: b.building_name for b in frappe.get_all(
        "Building", fields=["name", "building_name"])}
    out["rows"] = sorted(
        ({"building": b, "label": names.get(b, b), "amount": v}
         for b, v in out["by_building"].items()),
        key=lambda r: -r["amount"])
    return out
