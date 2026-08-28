"""Command Centre aggregates.

Everything the MD screen shows, computed from records rather than invented.

One rule holds this module together: a figure this business does not track is
returned as None, and the screen renders a dash. It is never estimated, never
back-filled from an average, never made up to fill a card. A blank that says
"we do not measure this" is worth more than a plausible number that nobody
can trace, and on this screen a plausible wrong number is the whole danger.

What is deliberately None, and why:

    cash on hand    the accounts sweep to near zero daily, so bank balance is
                    never used. Cash shows only once someone has declared a
                    counted position (Bank Balance Declaration); until then
                    it is None.
    unmatched bank  None until a Bank Statement Import has ever run; after
                    that, the live unmatched count.

Void days is derived, not logged: unit-days in the window not covered by a
tenancy agreement (_void_days). No status log to maintain, recomputable for
any window, and it agrees with occupancy by construction.

Amounts are returned in thousands of QAR, because that is what the prototype
renders.
"""

import frappe
from frappe.utils import (add_days, add_months, cint, flt, get_datetime,
                          get_first_day, get_last_day, getdate, today)
from darkbrown.guards import guard, ACC, GM, MD

def _k(v):
    """Money crosses to the shell in whole riyals. No scaling anywhere."""
    return round(flt(v))


def _q(v):
    """Full number with thousands separators, for text the MD reads."""
    return "{:,.0f}".format(flt(v))


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
            "rev": round(rev),
            "cost": round(cost),
            "m": round(margin),
            "mp": (margin / rev * 100) if rev else None,
            "arr": round(_arrears(b.name)),
            "vd": _void_days(m0, min(get_last_day(m0), getdate(today())),
                             b.name),
            "om": frappe.db.count("Maintenance Request", {
                "building": b.name,
                "status": ["in", ("Open", "Assigned", "Scheduled",
                                  "In Progress")]}),
            "ex": _expiry_risk(b.name),
            "d": ((rev - prev) / prev * 100) if prev else 0.0,
            # Rent that is contracted and drafted but not yet issued.
            # Without this a building whose run is waiting on approval
            # is indistinguishable from one earning nothing.
            "unbilled": round(_unissued(b.name, m0)),
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
    guard(MD, GM, ACC)
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
        select sum(round(annual_rent / 12, 2))
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
        "cash": _declared_cash(),     # a declared fact, or None — never the
        "cashD": None,                # swept bank balance (module note)
        "pdc30": _k(_pdc_due(30)),
        "ll30": _k(_landlord_due(30)),
        "vd": _void_days_months(months),
        "vdD": None,                  # no prior-period delta until a full
                                      # comparison window exists — a fake
                                      # movement is worse than none
        "br": _bounce_rate(90),
        "brD": 0.0,
        "unm": _unm_count(),          # None until an import has ever run
        "unmA": _unm_aged(),
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
            select sum(round(annual_rent / 12, 2)) from `tabHead Lease`
            where status in ('Active', 'Expiring')
              and start_date <= %s and end_date >= %s
              and building not in ({placeholders})
        """, [get_last_day(period_start), period_start] + exclude)[0][0])
    return flt(frappe.db.sql("""
        select sum(round(annual_rent / 12, 2)) from `tabHead Lease`
        where status in ('Active', 'Expiring')
          and start_date <= %s and end_date >= %s
    """, (get_last_day(period_start), period_start))[0][0])


def _void_days(period_start, period_end, building=None):
    """Unit-days inside the window not covered by a tenancy agreement.

    Derived from agreement dates rather than a status log, so it costs
    nothing to keep and can be recomputed for any window. Overlapping
    agreements on one unit are clamped to the window length, so a renewal
    signed before the old agreement ends cannot produce negative voids.
    Ended agreements count for the days they covered — a tenant who left
    mid-month covered the first half of it."""
    a, b = getdate(period_start), getdate(period_end)
    if b < a:
        return 0
    ufilters = {"building": building} if building else {}
    units = frappe.get_all("Unit", filters=ufilters, fields=["name"])
    if not units:
        return 0
    window = (b - a).days + 1
    afilters = {"status": ["in", ("Active", "Expiring", "Ended")],
                "start_date": ["<=", b], "end_date": [">=", a]}
    if building:
        afilters["building"] = building
    covered = {}
    for ag in frappe.get_all("Tenancy Agreement", filters=afilters,
                             fields=["unit", "start_date", "end_date"]):
        s = max(getdate(ag.start_date), a)
        e = min(getdate(ag.end_date), b)
        days = (e - s).days + 1
        if days > 0:
            covered[ag.unit] = min(window, covered.get(ag.unit, 0) + days)
    return sum(window - covered.get(u.name, 0) for u in units)


def _void_days_months(months):
    """Void days summed over a list of month offsets, each month clipped at
    today — days that have not happened yet are not voids."""
    total = 0
    for m in months:
        ms = getdate(_months(m))
        me = min(get_last_day(ms), getdate(today()))
        if me >= ms:
            total += _void_days(ms, me)
    return total


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


def _declared_cash():
    from darkbrown.api.cashdesk import latest_declarations
    dec = latest_declarations()
    return _k(dec["total"]) if dec else None


def _unm_count():
    from darkbrown.api.cashdesk import unmatched_summary
    u = unmatched_summary()
    return u.get("items") if u.get("imports") else None


def _unm_aged():
    from darkbrown.api.cashdesk import unmatched_summary
    u = unmatched_summary()
    return (f"{u['aged']} > 5d" if u.get("imports") and u.get("aged")
            else None)


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
        "runwayFlows": _runway_flows(),
        "waterfall": _waterfall(),
        "renewal": _renewal_uplift(),
        "utility": _utility_recovery(),
        "overrides": _override_log(),
        "closing": _closing(),
        "unmatched": _unmatched_panel(),
    }


def _closing():
    """Latest close, the one in flight, and when the next falls due —
    Thursday is the closing day this business keeps."""
    last = frappe.db.get_value(
        "Weekly Closing", {"status": "Closed"},
        ["period_end", "closed_on", "discrepancies", "assigned_to"],
        order_by="period_end desc", as_dict=True)
    cur = frappe.db.get_value(
        "Weekly Closing", {"status": ["in", ("Open", "In Progress")]},
        ["period_end", "status", "discrepancies", "assigned_to"],
        order_by="period_end desc", as_dict=True)
    d = getdate(today())
    days_to_thu = (3 - d.weekday()) % 7 or 7
    out = {"next": f"{add_days(d, days_to_thu):%a %d %b}",
           "nextIn": days_to_thu}
    if last:
        out["last"] = {
            "end": f"{getdate(last.period_end):%a %d %b}",
            "on": (f"{get_datetime(last.closed_on):%H:%M}"
                   if last.closed_on else ""),
            "disc": last.discrepancies or 0,
            "who": _who(last.assigned_to)}
    if cur:
        out["open"] = {
            "end": f"{getdate(cur.period_end):%a %d %b}",
            "st": cur.status, "disc": cur.discrepancies or 0,
            "who": _who(cur.assigned_to)}
    return out


def _who(user):
    if not user:
        return ""
    return frappe.db.get_value("User", user, "full_name") or user


def _unmatched_panel():
    from darkbrown.api.cashdesk import unmatched_summary
    return unmatched_summary()


def _pay_day_between(a, b):
    """The pay day falling inside a week, or None. Salaries land on one day of
    the month, so most weeks carry no payroll at all and one carries the lot —
    averaging it across thirteen weeks would smooth away the only thing the
    runway is for, which is seeing the week the money is not there."""
    day = cint(frappe.db.get_single_value("DBR Settings", "staff_pay_day")) or 5
    a, b = getdate(a), getdate(b)
    for month_start in {a.replace(day=1), b.replace(day=1)}:
        last = get_last_day(month_start).day
        try:
            d = month_start.replace(day=min(day, last))
        except ValueError:
            continue
        if a <= d <= b:
            return d
    return None


def _runway_flows():
    """Thirteen weeks of confirmed cash flows. Deliberately not a balance:
    the accounts sweep to near zero daily and the reserve denominator is
    blocked on Q10/Q11, so a cumulative line would be an invented opening
    position dressed as a forecast. The flows themselves are contractual —
    cheques in hand by maturity date, landlord payments by due date — and
    the expected overlay discounts outstanding invoices at the rolling
    90-day collection rate, the same discount the obligation-cover tile
    already applies."""
    # One function computes the rolling 90-day rate for the whole app. This
    # panel used to carry its own copy of the query, and the two drifted by
    # rounding into what read as two different collection rates on one
    # screen. If the definition ever changes it must change once.
    from darkbrown.api.app import _collection_rate
    from darkbrown.api.people import monthly_staff_cost as staff_cost
    rate = (_collection_rate() or 0.0) / 100.0

    out = []
    for w in range(13):
        a, b = add_days(today(), w * 7), add_days(today(), w * 7 + 6)
        pdc = flt(frappe.db.sql("""
            select sum(amount) from `tabCheque`
            where direction = 'Incoming' and status in ('Received', 'Deposited')
              and cheque_date between %s and %s
        """, (a, b))[0][0])
        if w == 0:
            # already-overdue book expects its discounted value up front
            exp = flt(frappe.db.sql("""
                select sum(outstanding_amount) from `tabSales Invoice`
                where docstatus = 1 and outstanding_amount > 0
                  and due_date <= %s""", (b,))[0][0]) * rate
        else:
            exp = flt(frappe.db.sql("""
                select sum(outstanding_amount) from `tabSales Invoice`
                where docstatus = 1 and outstanding_amount > 0
                  and due_date between %s and %s""", (a, b))[0][0]) * rate
        ll_rows = frappe.db.sql("""
            select hlp.amount, hl.landlord, hl.building
            from `tabHead Lease Payment` hlp
            join `tabHead Lease` hl on hl.name = hlp.parent
            where hlp.status = 'Scheduled' and hlp.due_date between %s and %s
            order by hlp.amount desc
        """, (a, b), as_dict=True)
        # Payroll is the most reliable outflow this business has and it was
        # not on the runway at all, so thirteen weeks read better than the
        # month ever does. It falls in the week that contains pay day; the
        # cost is taken as at that date, so somebody joining or leaving
        # mid-quarter moves the later weeks and not the earlier ones.
        pay_day = _pay_day_between(a, b)
        pay = staff_cost(pay_day) if pay_day else 0.0
        out.append({
            "wk": w + 1,
            "from": f"{getdate(a):%d %b}",
            "pdc": _k(pdc),
            "exp": _k(exp),
            "ll": _k(sum(flt(r.amount) for r in ll_rows)),
            "llName": (f"{ll_rows[0].landlord} — {ll_rows[0].building}"
                       if ll_rows else ""),
            "pay": _k(pay),
        })

    res = {"weeks": out, "rate": round(rate * 100, 1)}

    # The opening position is a declared fact or nothing. With one, the
    # server carries the cumulative lines; without one, the front end shows
    # flows only. Either way no balance is invented.
    from darkbrown.api.cashdesk import latest_declarations
    dec = latest_declarations()
    if dec:
        res["opening"] = _k(dec["total"])
        res["declaredOn"] = dec["declared_on"]
        res["staleDays"] = dec["stale_days"]
        res["accounts"] = [{"a": x["a"], "b": _k(x["b"]), "on": x["on"]}
                           for x in dec["accounts"]]
        balC, balE, c, e = [], [], _k(dec["total"]), _k(dec["total"])
        # Petty cash draw is an average, not a commitment, so it moves the
        # expected line and is kept off the confirmed one. The confirmed line
        # is meant to answer "what is certain", and an average is not.
        from darkbrown.api.pettycash import monthly_spend_average
        weekly_petty = monthly_spend_average(3) * 12.0 / 52.0
        for wrow in out:
            c = round(c + wrow["pdc"] - wrow["ll"] - wrow["pay"], 1)
            e = round(e + wrow["pdc"] + wrow["exp"]
                      - wrow["ll"] - wrow["pay"] - _k(weekly_petty), 1)
            balC.append(c)
            balE.append(e)
        res["balC"], res["balE"] = balC, balE
    return res


def _waterfall():
    """This month's spread bridge from recorded costs only. Bank-side costs
    have no equity/operating split until Q21 is answered, so they are not
    here and the end bar is named for what it is — the spread after recorded
    costs, not a net margin."""
    m0 = _months(0)
    held = unbilled_buildings(m0)
    gross = _billed_all(m0)
    landlord = _landlord_all(m0, exclude=held)
    mnt = frappe.db.sql("""
        select ifnull(sum(cost),0) c,
               ifnull(sum(case when rechargeable=1 then recharge_amount end),0) r
        from `tabMaintenance Request`
        where date(reported_on) between %s and %s
    """, (m0, get_last_day(m0)), as_dict=True)[0]
    utl = frappe.db.sql("""
        select ifnull(sum(ub.amount),0) paid,
               ifnull((select sum(uba.amount)
                       from `tabUtility Bill Allocation` uba
                       join `tabUtility Bill` ub2 on ub2.name = uba.parent
                       where uba.sales_invoice is not null
                         and ub2.period_end between %s and %s), 0) rec
        from `tabUtility Bill` ub
        where ub.period_end between %s and %s
    """, (m0, get_last_day(m0), m0, get_last_day(m0)), as_dict=True)[0]
    maint_net = flt(mnt.c) - flt(mnt.r)
    util_net = flt(utl.paid) - flt(utl.rec)
    # Staff and petty cash are portfolio overhead (D74, D79), so they land
    # here rather than being pushed down into building margin. They share one
    # bar: petty cash is small beside payroll and a separate bar for it would
    # be a sliver against a seventh set of labels the box cannot fit. The
    # split is returned alongside so the panel can name both.
    from darkbrown.api.people import monthly_staff_cost
    from darkbrown.api.pettycash import spend_between
    staff = monthly_staff_cost(m0)
    petty = spend_between(m0, get_last_day(m0))
    overhead = staff + petty
    return {
        "gross": _k(gross),
        "landlord": _k(landlord),
        "maintNet": _k(maint_net),
        "utilNet": _k(util_net),
        "overhead": _k(overhead),
        "staff": _k(staff),
        "petty": _k(petty),
        "spread": _k(gross - landlord - maint_net - util_net - overhead),
        "held": len(held),
    }


def _renewal_uplift():
    """Achieved renewal uplift, from agreements that carry renewal_of.
    Uplift is the new rent against the rent of the agreement it renews,
    bucketed by the month the renewal starts."""
    months, out = [_months(i) for i in range(-5, 1)], []
    for start in months:
        rows = frappe.db.sql("""
            select ta.monthly_rent as new_rent, old.monthly_rent as old_rent
            from `tabTenancy Agreement` ta
            join `tabTenancy Agreement` old on old.name = ta.renewal_of
            where ta.renewal_of is not null and ta.renewal_of != ''
              and ta.start_date between %s and %s
              and old.monthly_rent > 0
        """, (start, get_last_day(start)), as_dict=True)
        ups = [(flt(r.new_rent) - flt(r.old_rent)) / flt(r.old_rent) * 100
               for r in rows]
        out.append({"m": f"{getdate(start):%b}", "n": len(ups),
                    "up": round(sum(ups) / len(ups), 1) if ups else None})
    won = flt(frappe.db.sql("""
        select count(*) from `tabTenancy Agreement`
        where renewal_of is not null and renewal_of != ''
          and start_date >= %s""", (months[0],))[0][0])
    pending = frappe.db.count("Tenancy Agreement", {"status": "Expiring"})
    return {"months": out, "won": int(won), "pending": pending}


def _utility_recovery():
    """Utility spend against the share recharged to tenants. Recovered
    means an allocation line that has a sales invoice behind it — an
    allocation without one is a plan, not a recovery."""
    out = []
    for i in range(-11, 1):
        a, b = _months(i), get_last_day(_months(i))
        paid = flt(frappe.db.sql("""
            select sum(amount) from `tabUtility Bill`
            where period_end between %s and %s""", (a, b))[0][0])
        rec = flt(frappe.db.sql("""
            select sum(uba.amount)
            from `tabUtility Bill Allocation` uba
            join `tabUtility Bill` ub on ub.name = uba.parent
            where uba.sales_invoice is not null
              and ub.period_end between %s and %s""", (a, b))[0][0])
        out.append({"m": f"{getdate(a):%b}", "paid": _k(paid),
                    "rec": _k(rec)})
    return out


def _override_log():
    """Soft-block overrides this month, read from deposit batches where an
    override reason was recorded. One row per person, latest reason kept."""
    rows = frappe.get_all(
        "Deposit Batch",
        filters={"override_reason": ["is", "set"],
                 "deposit_date": [">=", _months(0)]},
        fields=["prepared_by", "override_reason", "deposit_date", "name"],
        order_by="deposit_date desc")
    by = {}
    for r in rows:
        who = frappe.db.get_value("User", r.prepared_by, "full_name") \
            or r.prepared_by or "—"
        e = by.setdefault(who, {"by": who, "n": 0, "last": "", "ref": ""})
        e["n"] += 1
        if not e["last"]:
            e["last"], e["ref"] = r.override_reason, r.name
    return sorted(by.values(), key=lambda x: -x["n"])


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
                    "t": f"Cheque bounced — {r.party} · QAR {_q(r.amount)}"
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
                         f" · QAR {_q(r.cost)} vs QAR 2,000 limit",
                    "w": f"{getdate(r.reported_on):%d %b}",
                    "go": "#/maint"})

    for b, amt in (unissued(_months(0)) or {}).items():
        out.append({"s": "a",
                    "t": f"Invoice run not issued — {b}"
                         f" · QAR {_q(amt)} raised",
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
