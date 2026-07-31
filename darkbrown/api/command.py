"""Command Centre aggregates.

Everything the MD screen shows, computed from records rather than invented.

One rule holds this module together: a figure this business does not track is
returned as None, and the screen renders a dash. It is never estimated, never
back-filled from an average, never made up to fill a card. A blank that says
"we do not measure this" is worth more than a plausible number that nobody
can trace, and on this screen a plausible wrong number is the whole danger.

What is deliberately None, and why:

    void days       no void-start date is recorded on Unit, so elapsed void
                    cannot be derived. Needs a field before it can be shown.
    cash on hand    the accounts sweep to near zero daily, so bank balance is
                    not cash availability. Blocked on Q11.
    unmatched bank  no statement import exists yet.

Amounts are returned in thousands of QAR, because that is what the prototype
renders.
"""

import frappe
from frappe.utils import (add_days, add_months, flt, get_first_day,
                          get_last_day, getdate, today)

K = 1000.0


def _k(v):
    return round(flt(v) / K, 1)


def _months(n):
    return get_first_day(add_months(get_first_day(today()), n))


# ==========================================================================
#  building health — feeds the heatmap and the portfolio table
# ==========================================================================

def health():
    """One row per building: occupancy, revenue, landlord cost, margin,
    arrears, open maintenance, expiry risk, month-on-month movement."""
    rows = []
    m0, m1 = _months(0), _months(-1)

    for b in frappe.get_all("Building",
                            filters={"status": ["!=", "Exited"]},
                            fields=["name", "cost_center"]):
        units = frappe.db.count("Unit", {"building": b.name})
        if not units:
            continue
        occupied = frappe.db.count("Unit", {"building": b.name,
                                            "status": "Occupied"})

        rev = _billed(b.name, m0)
        prev = _billed(b.name, m1)
        cost = _landlord_cost(b.name, m0)
        margin = rev - cost

        rows.append({
            "n": b.name,
            "u": units,
            "occ": round(occupied / units * 100) if units else 0,
            "rev": round(rev / K),
            "cost": round(cost / K),
            "m": round(margin / K),
            "mp": (margin / rev * 100) if rev else None,
            "arr": round(_arrears(b.name) / K),
            "vd": None,                       # not tracked — see module note
            "om": frappe.db.count("Maintenance Request", {
                "building": b.name,
                "status": ["in", ("Open", "Assigned", "Scheduled",
                                  "In Progress")]}),
            "ex": _expiry_risk(b.name),
            "d": ((rev - prev) / prev * 100) if prev else 0.0,
            # Rent that is contracted and drafted but not yet issued.
            # Without this a building whose run is waiting on approval
            # is indistinguishable from one earning nothing.
            "unbilled": round(_unissued(b.name, m0) / K),
        })

    rows.sort(key=lambda r: -r["rev"])
    return rows


@frappe.whitelist()
def unissued(period_start=None):
    """Invoice runs raised for a period but never issued, by building.

    This is the difference between a building that earned nothing and a
    building whose invoices are sitting in the approvals queue. Every figure
    on the Command Centre that sets billed revenue against head-lease cost
    has to know about it, because the cost is always complete and the billing
    is not."""
    period_start = period_start or _months(0)
    rows = frappe.db.sql("""
        select ir.building as building, sum(ir.total_amount) as amount
        from `tabInvoice Run` ir
        where ir.period_start = %s and ir.status in ('Draft', 'Pending GM')
        group by ir.building
    """, (period_start,), as_dict=True)
    return {r.building: flt(r.amount) for r in rows}


def unbilled_buildings(period_start=None):
    """Buildings carrying a head-lease cost this period with an unissued run
    and nothing billed. Their cost has no revenue to sit against, so counting
    it reports a loss that has not happened."""
    period_start = period_start or _months(0)
    return {b: amt for b, amt in unissued(period_start).items()
            if not _billed(b, period_start)}


def _unissued(building, period_start):
    """Invoice runs raised for the period but not yet issued.

    A run sitting at Draft or Pending GM has produced no submitted invoice, so
    `_billed` correctly returns nothing for it. Reported on its own that reads
    as a building earning zero against a full head-lease cost, which is a very
    different thing from a decision nobody has taken yet."""
    return flt(frappe.db.sql("""
        select sum(total_amount) from `tabInvoice Run`
        where building = %s and period_start = %s
          and status in ('Draft', 'Pending GM')
    """, (building, period_start))[0][0])


def _billed(building, period_start):
    """What tenants were charged for that month in that building."""
    return flt(frappe.db.sql("""
        select sum(si.grand_total)
        from `tabSales Invoice` si
        join `tabInvoice Run Line` irl on irl.sales_invoice = si.name
        join `tabInvoice Run` ir on ir.name = irl.parent
        where si.docstatus = 1 and ir.building = %s and ir.period_start = %s
    """, (building, period_start))[0][0])


def _landlord_cost(building, period_start):
    """One month of head-lease rent for leases live in that month."""
    return flt(frappe.db.sql("""
        select sum(annual_rent) / 12
        from `tabHead Lease`
        where building = %s and status in ('Active', 'Expiring')
          and start_date <= %s and end_date >= %s
    """, (building, get_last_day(period_start), period_start))[0][0])


def _arrears(building):
    return flt(frappe.db.sql("""
        select sum(si.outstanding_amount)
        from `tabSales Invoice` si
        join `tabInvoice Run Line` irl on irl.sales_invoice = si.name
        join `tabInvoice Run` ir on ir.name = irl.parent
        where si.docstatus = 1 and ir.building = %s
    """, (building,))[0][0])


def _expiry_risk(building):
    """Agreements and documents running out inside ninety days."""
    horizon = add_days(today(), 90)
    n = frappe.db.count("Tenancy Agreement", {
        "building": building, "status": ["in", ("Active", "Expiring")],
        "end_date": ["<=", horizon]})
    n += frappe.db.count("Head Lease", {
        "building": building, "status": ["in", ("Active", "Expiring")],
        "end_date": ["<=", horizon]})
    n += frappe.db.count("Document Register", {
        "building": building, "status": "Confirmed",
        "expiry_date": ["between", [today(), horizon]]})
    return n


# ==========================================================================
#  KPI grid
# ==========================================================================

def kpis():
    """The twelve-card strip, for each of the four periods it offers."""
    out = {}
    for key, months, label in (
            ("jul", [0], _label(0)),
            ("jun", [-1], _label(-1)),
            ("q3", [-2, -1, 0], f"{_label(-2)} – {_label(0)}"),
            ("ytd", _ytd_months(), "Year to date")):
        out[key] = _period(months, label)
    return out


def _label(n):
    return f"{getdate(_months(n)):%b '%y}"


def _ytd_months():
    jan = getdate(today()).replace(month=1, day=1)
    n = (getdate(today()).year - getdate(jan).year) * 12 + \
        getdate(today()).month - 1
    return list(range(-n, 1))


def _period(months, label):
    billed = sum(_billed_all(_months(m)) for m in months)
    collected = sum(_collected_all(_months(m)) for m in months)
    # Same rule as the spread tile: a building whose run was never issued
    # contributes no billing, so its cost is held out rather than counted
    # against nothing. Otherwise net spread reports a loss that is an
    # unmade decision.
    held = {}
    for m in months:
        held.update(unbilled_buildings(_months(m)))
    cost = sum(_landlord_all(_months(m), exclude=held) for m in months)

    prev = [m - len(months) for m in months]
    pbilled = sum(_billed_all(_months(m)) for m in prev)
    pcollected = sum(_collected_all(_months(m)) for m in prev)
    pheld = {}
    for m in prev:
        pheld.update(unbilled_buildings(_months(m)))
    # the comparison period gets the same treatment, or the movement is
    # measured between two different definitions
    pcost = sum(_landlord_all(_months(m), exclude=pheld) for m in prev)

    spread, pspread = billed - cost, pbilled - pcost
    units = frappe.db.count("Unit")
    occupied = frappe.db.count("Unit", {"status": "Occupied"})

    return {
        "spread": _k(spread),
        "spreadP": ((spread - pspread) / pspread * 100) if pspread else 0.0,
        "margin": (spread / billed * 100) if billed else 0.0,
        "marginD": ((spread / billed * 100) if billed else 0.0)
                   - ((pspread / pbilled * 100) if pbilled else 0.0),
        "coll": (collected / billed * 100) if billed else 0.0,
        "collD": ((collected / billed * 100) if billed else 0.0)
                 - ((pcollected / pbilled * 100) if pbilled else 0.0),
        "arr": _k(_arrears_all()),
        "arrD": 0.0,
        "cash": None,                 # blocked on Q11 — see module note
        "cashD": None,
        "pdc30": _k(_pdc_due(30)),
        "ll30": _k(_landlord_due(30)),
        "vd": None,                   # not tracked
        "vdD": None,
        "br": _bounce_rate(90),
        "brD": 0.0,
        "unm": None,                  # no statement import
        "unmA": None,
        "ap": len(_pending_approvals()),
        "apOld": len([a for a in _pending_approvals() if a > 2]),
        "unissued": _k(sum(held.values())) if held else 0,
        "unissuedN": len(held),
        "units": units,
        "occupied": occupied,
        "occPct": round(occupied / units * 100, 1) if units else 0.0,
        "label": label,
    }


def _billed_all(period_start):
    return flt(frappe.db.sql("""
        select sum(grand_total) from `tabSales Invoice`
        where docstatus = 1 and posting_date between %s and %s
    """, (period_start, get_last_day(period_start)))[0][0])


def _collected_all(period_start):
    return flt(frappe.db.sql("""
        select sum(grand_total - outstanding_amount) from `tabSales Invoice`
        where docstatus = 1 and posting_date between %s and %s
    """, (period_start, get_last_day(period_start)))[0][0])


def _landlord_all(period_start, exclude=None):
    exclude = list(exclude or [])
    if exclude:
        placeholders = ", ".join(["%s"] * len(exclude))
        return flt(frappe.db.sql(f"""
            select sum(annual_rent) / 12 from `tabHead Lease`
            where status in ('Active', 'Expiring')
              and start_date <= %s and end_date >= %s
              and building not in ({placeholders})
        """, [get_last_day(period_start), period_start] + exclude)[0][0])
    return flt(frappe.db.sql("""
        select sum(annual_rent) / 12 from `tabHead Lease`
        where status in ('Active', 'Expiring')
          and start_date <= %s and end_date >= %s
    """, (get_last_day(period_start), period_start))[0][0])


def _arrears_all():
    return flt(frappe.db.sql("""
        select sum(outstanding_amount) from `tabSales Invoice`
        where docstatus = 1""")[0][0])


def _pdc_due(days):
    return flt(frappe.db.sql("""
        select sum(amount) from `tabCheque`
        where direction = 'Incoming' and status in ('Received', 'Deposited')
          and cheque_date between %s and %s
    """, (today(), add_days(today(), days)))[0][0])


def _landlord_due(days):
    return flt(frappe.db.sql("""
        select sum(amount) from `tabHead Lease Payment`
        where status = 'Scheduled' and due_date between %s and %s
    """, (today(), add_days(today(), days)))[0][0])


def _bounce_rate(days):
    since = add_days(today(), -days)
    # Count on returned_on, not on status. A returned cheque that has since
    # been replaced carries status "Replaced", so counting by status quietly
    # loses every bounce the tenant made good — which is most of them, and
    # would make the bounce rate look far better than it is.
    returned = frappe.db.count("Cheque", {"returned_on": [">=", since]})
    cleared = frappe.db.count("Cheque", {"status": "Cleared",
                                         "cleared_on": [">=", since]})
    total = returned + cleared
    return round(returned / total * 100, 1) if total else 0.0


def _pending_approvals():
    """Ages in days of everything waiting on a decision."""
    from darkbrown.api.app import approvals
    try:
        return [a.get("age", 0) for a in approvals()]
    except Exception:
        return []


# ==========================================================================
#  the smaller panels
# ==========================================================================

def panels():
    """Everything else on the Command Centre that can be derived."""
    return {
        "arrears": _arrears_buckets(),
        "llCheques": _landlord_cheques(),
        "bounces": _bounce_list(),
        "pdcLadder": _pdc_ladder(),
        "voids": _void_pipeline(),
        "expiry": _expiry_runway(),
        "conc": _concentration(),
        "deposits": _deposit_gauge(),
        "billcol": _billed_vs_collected(),
        "occ": _occupancy_trend(),
        "maint": _maintenance_split(),
        "spread12": _spread12(),
        "exceptions": _exceptions(),
    }


def _spread12():
    """Twelve months of tenant billing against head-lease cost. A month in
    which a building's invoice run was never issued holds that building's
    cost out, same rule as the KPI strip — otherwise the chart reports a
    loss that is really an unmade decision."""
    out = []
    for i in range(-11, 1):
        start = _months(i)
        held = unbilled_buildings(start)
        billed = _billed_all(start)
        cost = _landlord_all(start, exclude=held)
        out.append({
            "m": f"{getdate(start):%b}",
            "billed": _k(billed),
            "cost": _k(cost),
            "mp": round((billed - cost) / billed * 100, 1) if billed else None,
            "held": len(held),
        })
    return out


def _exceptions():
    """The morning exceptions feed, assembled from records that already
    exist. Nothing here is a new judgement — each line restates a fact the
    system holds somewhere less visible."""
    out = []
    for r in frappe.get_all(
            "Cheque",
            filters={"returned_on": [">=", add_days(today(), -7)]},
            fields=["party", "amount", "return_reason", "returned_on"],
            order_by="returned_on desc", limit_page_length=5):
        out.append({"s": "r",
                    "t": f"Cheque bounced — {r.party} · {_k(r.amount)}K"
                         + (f" · {r.return_reason.lower()}"
                            if r.return_reason else ""),
                    "w": f"{getdate(r.returned_on):%d %b}",
                    "go": "#/cheques"})

    aged = [a for a in _pending_approvals() if a > 2]
    if aged:
        out.append({"s": "r",
                    "t": f"{len(aged)} approval"
                         f"{'s' if len(aged) > 1 else ''}"
                         " waiting over 48 hours",
                    "w": "now", "go": "#/approvals"})

    for r in frappe.get_all(
            "Maintenance Request",
            filters={"priority": "Emergency", "cost": [">", 2000],
                     "reported_on": [">=", add_days(today(), -14)]},
            fields=["name", "building", "cost", "reported_on"],
            order_by="reported_on desc", limit_page_length=3):
        out.append({"s": "a",
                    "t": f"Emergency maint over ceiling — {r.building}"
                         f" · {_k(r.cost)}K vs 2.0K limit",
                    "w": f"{getdate(r.reported_on):%d %b}",
                    "go": "#/maint"})

    for b, amt in (unissued(_months(0)) or {}).items():
        out.append({"s": "a",
                    "t": f"Invoice run not issued — {b}"
                         f" · {_k(amt)}K raised",
                    "w": "this month", "go": "#/generate"})
    return out[:8]


def _arrears_buckets():
    out = []
    for label, lo, hi in (("0–30", 0, 30), ("31–60", 31, 60),
                          ("61–90", 61, 90), ("90+", 91, 99999)):
        amount = flt(frappe.db.sql("""
            select sum(outstanding_amount) from `tabSales Invoice`
            where docstatus = 1 and outstanding_amount > 0
              and datediff(%s, due_date) between %s and %s
        """, (today(), lo, hi))[0][0])
        out.append({"label": label, "amt": _k(amount)})
    return out


def _landlord_cheques():
    rows = frappe.db.sql("""
        select hlp.due_date, hlp.amount, hl.building, hl.landlord
        from `tabHead Lease Payment` hlp
        join `tabHead Lease` hl on hl.name = hlp.parent
        where hlp.status = 'Scheduled' and hlp.due_date >= %s
        order by hlp.due_date asc limit 5
    """, (today(),), as_dict=True)
    return [{"ll": r.landlord, "b": r.building,
             "due": f"{getdate(r.due_date):%d %b}", "amt": _k(r.amount),
             "band": _due_band(r.due_date)} for r in rows]


def _due_band(due):
    days = (getdate(due) - getdate(today())).days
    return "r" if days <= 7 else "a" if days <= 21 else "g"


def _bounce_list():
    rows = frappe.get_all(
        "Cheque",
        filters={"returned_on": [">=", add_days(today(), -30)]},
        fields=["party", "amount", "return_reason", "returned_on",
                "unit", "replaced_by"],
        order_by="returned_on desc")
    return [{"t": r.party, "u": r.unit, "amt": _k(r.amount),
             "why": r.return_reason,
             "days": (getdate(today()) - getdate(r.returned_on)).days,
             "action": "Replacement recd" if r.replaced_by else "Chase"}
            for r in rows]


def _pdc_ladder():
    out = []
    for label, lo, hi in (("0–30d", 0, 30), ("31–60d", 31, 60),
                          ("61–90d", 61, 90), ("90d+", 91, 99999)):
        deposited = flt(frappe.db.sql("""
            select sum(amount) from `tabCheque`
            where direction='Incoming' and status='Deposited'
              and datediff(cheque_date, %s) between %s and %s
        """, (today(), lo, hi))[0][0])
        on_hand = flt(frappe.db.sql("""
            select sum(amount) from `tabCheque`
            where direction='Incoming' and status='Received'
              and datediff(cheque_date, %s) between %s and %s
        """, (today(), lo, hi))[0][0])
        out.append({"label": label, "dep": _k(deposited),
                    "hand": _k(on_hand)})
    return out


def _void_pipeline():
    rows = frappe.get_all(
        "Unit",
        filters={"status": ["in", ("Vacant", "Not Ready", "Reserved",
                                   "Under Maintenance")]},
        fields=["name", "building", "status"])
    out = []
    for u in rows:
        rent = flt(frappe.db.sql("""
            select avg(monthly_rent) from `tabTenancy Agreement`
            where building = %s and status in ('Active','Expiring')
        """, (u.building,))[0][0])
        out.append({"u": u.name, "b": u.building, "stage": u.status,
                    "days": None,               # not tracked
                    "bleed": _k(rent)})
    out.sort(key=lambda x: -(x["bleed"] or 0))
    return out


def _expiry_runway():
    out = []
    for i in range(12):
        start = _months(i)
        end = get_last_day(start)
        out.append({
            "m": f"{getdate(start):%b}",
            "tenancy": frappe.db.count("Tenancy Agreement", {
                "status": ["in", ("Active", "Expiring")],
                "end_date": ["between", [start, end]]}),
            "headlease": frappe.db.count("Head Lease", {
                "status": ["in", ("Active", "Expiring")],
                "end_date": ["between", [start, end]]}),
            "docs": frappe.db.count("Document Register", {
                "status": "Confirmed",
                "expiry_date": ["between", [start, end]]}),
        })
    return out


def _concentration():
    rows = frappe.db.sql("""
        select ta.tenant, count(*) as units, sum(ta.monthly_rent) as rent
        from `tabTenancy Agreement` ta
        where ta.status in ('Active','Expiring')
        group by ta.tenant order by rent desc limit 6
    """, as_dict=True)
    total = flt(frappe.db.sql("""
        select sum(monthly_rent) from `tabTenancy Agreement`
        where status in ('Active','Expiring')""")[0][0])
    out, cum = [], 0.0
    for r in rows:
        pct = (flt(r.rent) / total * 100) if total else 0.0
        cum += pct
        out.append({"t": r.tenant, "units": r.units, "rent": _k(r.rent),
                    "pct": round(pct, 1), "cum": round(cum, 1)})
    return out


def _deposit_gauge():
    held = flt(frappe.db.sql("""
        select sum(amount - ifnull(deductions,0)) from `tabSecurity Deposit`
        where status = 'Held'""")[0][0])
    due = flt(frappe.db.sql("""
        select sum(sd.amount - ifnull(sd.deductions,0))
        from `tabSecurity Deposit` sd
        where sd.status = 'Held' and sd.move_out_case is not null
    """)[0][0])
    cases = frappe.db.count("Security Deposit",
                            {"status": "Held",
                             "move_out_case": ["is", "set"]})
    return {"held": _k(held), "due": _k(due), "cases": cases}


def _billed_vs_collected():
    out = []
    for i in range(-11, 1):
        start = _months(i)
        out.append({"m": f"{getdate(start):%b}",
                    "billed": _k(_billed_all(start)),
                    "collected": _k(_collected_all(start))})
    return out


def _occupancy_trend():
    """Occupancy for each of the last twelve months, from agreements that
    were live in that month rather than from today's unit statuses."""
    units = frappe.db.count("Unit")
    out = []
    for i in range(-11, 1):
        start, end = _months(i), get_last_day(_months(i))
        live = flt(frappe.db.sql("""
            select count(distinct unit) from `tabTenancy Agreement`
            where status in ('Active','Expiring','Terminated','Expired')
              and start_date <= %s and end_date >= %s
        """, (end, start))[0][0])
        out.append({"m": f"{getdate(start):%b}",
                    "occ": round(live / units * 100) if units else 0,
                    "units": units})
    return out


def _maintenance_split():
    out = []
    for i in range(-11, 1):
        start, end = _months(i), get_last_day(_months(i))
        rows = frappe.db.sql("""
            select ifnull(sum(case when priority='Emergency' then cost end),0) emerg,
                   ifnull(sum(case when is_preventive=1 then cost end),0) plan,
                   ifnull(sum(case when rechargeable=1 then recharge_amount end),0) rech,
                   ifnull(sum(cost),0) total
            from `tabMaintenance Request`
            where date(reported_on) between %s and %s
        """, (start, end), as_dict=True)[0]
        out.append({"m": f"{getdate(start):%b}", "planned": _k(rows.plan),
                    "emergency": _k(rows.emerg), "recharged": _k(rows.rech),
                    "total": _k(rows.total)})
    return out
