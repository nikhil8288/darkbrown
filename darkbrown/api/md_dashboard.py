"""Read-only data methods for the Managing Director dashboard.

Design rule: every method returns the same shape whether or not records
exist. Empty means empty arrays and zeroes, never a missing key and never
a mock. The frontend renders "no data yet" states from the numbers alone,
so nothing has to change when the first invoice posts.

Sources
    Portfolio / Tenants   Building, Unit, Tenant Rental Agreement,
                          Landlord Contract        (populated now)
    Finance               Sales Invoice, Purchase Invoice, PDC Cheque,
                          GL Entry                  (from 2026-07-01)
    History               Historical Monthly PL     (imported from Excel)
    Maintenance           Maintenance Request       (new)
    Alerts                derived from all of the above

Every method re-checks the role server-side. Permission is not the
frontend's job.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, flt, cint, formatdate, add_days

_ALLOWED = {"Managing Director", "System Manager", "Administrator"}

# An Active lease ending within this many days is treated as "on notice".
NOTICE_WINDOW = 60

# How far ahead we look for expiries, both tenant and landlord side.
EXPIRY_WINDOW = 90

# ERPNext starts carrying real money from this date. Before it, the manual
# Excel books are authoritative and live in Historical Monthly PL.
GENERATION_START = "2026-07-01"

# Tenant cheques from payers with bounce history are discounted before
# they are allowed into a forward-cash figure.
BOUNCE_HAIRCUT = 0.35


def _guard():
    if not (set(frappe.get_roles(frappe.session.user)) & _ALLOWED):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _has(doctype):
    """True when the DocType exists on this site. Lets the dashboard ship
    ahead of the DocTypes it will eventually read."""
    return frappe.db.exists("DocType", doctype)


def _days_until(d):
    return None if not d else (getdate(d) - getdate(nowdate())).days


def _fmt(d):
    return formatdate(d, "dd MMM yyyy") if d else ""


def _company():
    return frappe.defaults.get_user_default("Company") or frappe.db.get_value(
        "Company", {}, "name"
    )


# --------------------------------------------------------------- fetchers

def _active_leases():
    return frappe.get_all(
        "Tenant Rental Agreement",
        filters={"status": "Active"},
        fields=["name", "tenant", "building", "unit", "monthly_rent",
                "start_date", "end_date", "security_deposit"],
    )


def _landlord_contracts():
    return frappe.get_all(
        "Landlord Contract",
        filters={"status": "Active"},
        fields=["name", "landlord", "building", "total_owner_rent",
                "contract_start_date", "contract_end_date", "grace_period_days"],
    )


def _customer_names():
    return {c.name: c.customer_name
            for c in frappe.get_all("Customer", fields=["name", "customer_name"])}


def _unit_labels():
    return {u.name: (u.unit_no or u.unit_name or u.name)
            for u in frappe.get_all("Unit", fields=["name", "unit_no", "unit_name"])}


def _unit_status(unit, lease):
    """Unit stores only Vacant|Occupied. Notice is derived from the lease."""
    if unit.occupancy_status == "Vacant":
        return "Vacant"
    if lease:
        d = _days_until(lease.end_date)
        if d is not None and 0 <= d <= NOTICE_WINDOW:
            return "Notice"
    return "Occupied"


# -------------------------------------------------------------- portfolio

@frappe.whitelist()
def get_portfolio():
    """buildings: [name, income_K, headlease_K, total, vacant, expiry,
                   at_risk, leak_pct]
       units:     [bldg, unit, status, tenant, rent_K, vac_days,
                   furnish, type, move_out]"""
    _guard()

    units = frappe.get_all(
        "Unit",
        fields=["name", "unit_no", "unit_name", "building", "unit_type",
                "monthly_rent", "occupancy_status", "furnishing_status"],
    )
    leases = {l.unit: l for l in _active_leases() if l.unit}
    contracts = {c.building: c for c in _landlord_contracts()}
    cust = _customer_names()

    unit_rows, by_building = [], {}

    for u in units:
        lease = leases.get(u.name)
        status = _unit_status(u, lease)
        # Contracted rent when let; asking rent when empty.
        rent = flt(lease.monthly_rent) if lease else flt(u.monthly_rent)

        tenant = ""
        if lease:
            tenant = cust.get(lease.tenant) or "(unlinked tenant)"

        move_out = _fmt(lease.end_date) if (status == "Notice" and lease) else ""

        unit_rows.append([
            u.building,
            u.unit_no or u.unit_name or u.name,
            status,
            tenant,
            round(rent / 1000.0, 1),
            None,                      # vac_days: Unit has no vacant_since yet
            u.furnishing_status or "",
            u.unit_type or "",
            move_out,
        ])

        agg = by_building.setdefault(
            u.building, {"total": 0, "vacant": 0, "income": 0.0, "at_risk": 0})
        agg["total"] += 1
        if status == "Vacant":
            agg["vacant"] += 1
        else:
            agg["income"] += rent
        if status == "Notice":
            agg["at_risk"] += 1

    building_rows = []
    for bname, agg in by_building.items():
        c = contracts.get(bname)
        headlease = flt(c.total_owner_rent) if c else 0.0

        # Rent leakage: how far below asking the let units actually achieve.
        asking = sum(flt(u.monthly_rent) for u in units
                     if u.building == bname and u.occupancy_status == "Occupied")
        leak = 0
        if asking > 0 and agg["income"] < asking:
            leak = int(round((1 - agg["income"] / asking) * 100))

        building_rows.append([
            bname,
            round(agg["income"] / 1000.0, 1),
            round(headlease / 1000.0, 1),
            agg["total"],
            agg["vacant"],
            _fmt(c.contract_end_date) if c else "",
            agg["at_risk"],
            leak,
        ])

    building_rows.sort(key=lambda r: r[0])
    unit_rows.sort(key=lambda r: (r[0], r[1]))

    total_units = sum(b[3] for b in building_rows)
    total_vacant = sum(b[4] for b in building_rows)
    occ = ((total_units - total_vacant) / total_units * 100) if total_units else 0

    # Head-lease still payable on the share of each building that earns nothing.
    bleed = sum(
        flt(contracts[b[0]].total_owner_rent) * (b[4] / b[3])
        for b in building_rows if b[0] in contracts and b[3]
    )

    inc = sum(b[1] for b in building_rows)
    hl = sum(b[2] for b in building_rows)

    return {
        "live": True,
        "buildings": building_rows,
        "units": unit_rows,
        "strip": {
            "buildings": len(building_rows),
            "units": total_units,
            "vacant": total_vacant,
            "occupancy": round(occ, 1),
            "bleed": round(bleed / 1000.0, 1),
            "margin": round((inc - hl) / inc * 100, 1) if inc else 0,
        },
    }


# ---------------------------------------------------------------- tenants

def _arrears_by_customer():
    """Outstanding per Customer from submitted Sales Invoices. Empty dict
    until invoices exist, which keeps every caller's shape stable."""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["customer", "outstanding_amount", "due_date"],
    )
    out = {}
    for r in rows:
        e = out.setdefault(r.customer, {"amount": 0.0, "oldest": None})
        e["amount"] += flt(r.outstanding_amount)
        if r.due_date and (e["oldest"] is None or getdate(r.due_date) < e["oldest"]):
            e["oldest"] = getdate(r.due_date)
    return out


def _bounces_by_customer():
    if not _has("PDC Cheque"):
        return {}
    rows = frappe.get_all(
        "PDC Cheque",
        filters={"status": "Bounced"},
        fields=["name", "status"] + (
            ["tenant"] if frappe.get_meta("PDC Cheque").has_field("tenant") else []
        ),
    )
    out = {}
    for r in rows:
        t = r.get("tenant")
        if t:
            out[t] = out.get(t, 0) + 1
    return out


@frappe.whitelist()
def get_tenants():
    """tenants: [name, loc, rent_K, agreement, standing, outstanding_K,
                 bounces, since, ltv_M]"""
    _guard()

    agreements = frappe.get_all(
        "Tenant Rental Agreement",
        fields=["name", "tenant", "building", "unit", "monthly_rent",
                "status", "start_date", "end_date"],
        order_by="end_date asc",
    )
    cust = _customer_names()
    ulab = _unit_labels()
    arrears = _arrears_by_customer()
    bounces = _bounces_by_customer()

    tn_rows, expiring, other, notice = [], [], [], []
    active = expiring_soon = in_arrears = 0

    for a in agreements:
        name = cust.get(a.tenant)
        if not name:
            # Orphan agreement: Customer link null or deleted. Skip rather
            # than render a blank row.
            continue

        loc = "%s · %s" % (a.building or "", ulab.get(a.unit, a.unit or ""))
        days = _days_until(a.end_date)

        ar = arrears.get(a.tenant, {})
        outstanding = flt(ar.get("amount", 0))
        bc = cint(bounces.get(a.tenant, 0))
        if outstanding > 0:
            in_arrears += 1

        if a.status == "Active":
            active += 1
            if days is not None and 0 <= days <= EXPIRY_WINDOW:
                expiring_soon += 1
                state = "Expiring"
                expiring.append([name, loc, _fmt(a.end_date), "%d days" % days,
                                 "red" if days <= 30 else "orange"])
                notice.append([name, loc, _fmt(a.end_date), "Non-renewal"])
            else:
                state = "Active"
        elif a.status == "Expired":
            state = "Lapsed"
            other.append([name, "Lapsed · no current contract", "red"])
        elif a.status == "Terminated":
            continue
        else:
            state = "Active"

        tn_rows.append([
            name, loc, round(flt(a.monthly_rent) / 1000.0, 1), state,
            "arrears" if outstanding > 0 else "current",
            round(outstanding / 1000.0, 1),
            bc,
            _fmt(a.start_date)[3:] if a.start_date else "",
            0.0,   # lifetime collected: needs payment history, phase 3
        ])

    return {
        "live": True,
        "tenants": tn_rows,
        "expiring": expiring[:10],
        "other": other[:10],
        "notice": notice[:10],
        "churn_out": [],   # no move-out tracking yet
        "strip": {
            "active": active,
            "expiring": expiring_soon,
            "arrears": in_arrears,
            "lapsed": len(other),
            "notice": len(notice),
        },
    }


# ---------------------------------------------------------------- finance

def _ageing_buckets():
    """Four AR buckets. All zero until invoices exist."""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["outstanding_amount", "due_date"],
    )
    b = [0.0, 0.0, 0.0, 0.0]   # current, 1-30, 31-60, 60+
    today = getdate(nowdate())
    for r in rows:
        overdue = (today - getdate(r.due_date)).days if r.due_date else 0
        amt = flt(r.outstanding_amount)
        if overdue <= 0:
            b[0] += amt
        elif overdue <= 30:
            b[1] += amt
        elif overdue <= 60:
            b[2] += amt
        else:
            b[3] += amt

    peak = max(b) or 1
    labels = ["Current", "1–30 days", "31–60 days", "60+ days"]
    cols = ["#1E7E58", "#9A7A2E", "#A85A2C", "#BC512B"]
    return [
        [labels[i], "QAR %s" % _k(b[i]), "%d%%" % round(b[i] / peak * 100), cols[i]]
        for i in range(4)
    ]


def _k(v):
    """Render an amount the way the dashboard does: K under a million."""
    v = flt(v)
    return ("%.2fM" % (v / 1e6)) if abs(v) >= 1e6 else ("%.1fK" % (v / 1e3))


def _period_bounds(timeframe):
    from frappe.utils import get_first_day, get_last_day, add_months
    today = getdate(nowdate())
    if timeframe == "today":
        return today, today
    if timeframe == "quarter":
        q = (today.month - 1) // 3
        start = today.replace(month=q * 3 + 1, day=1)
        return start, get_last_day(add_months(start, 2))
    if timeframe == "year":
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    return get_first_day(today), get_last_day(today)


@frappe.whitelist()
def get_finance(timeframe="month"):
    """P&L, receivables, PDC and payables. Zeroes before 2026-07-01."""
    _guard()
    start, end = _period_bounds(timeframe)

    income = flt(frappe.db.get_value(
        "Sales Invoice",
        {"docstatus": 1, "posting_date": ["between", [start, end]]},
        "sum(base_grand_total)") or 0)

    collected = income - flt(frappe.db.get_value(
        "Sales Invoice",
        {"docstatus": 1, "posting_date": ["between", [start, end]]},
        "sum(outstanding_amount)") or 0)

    headlease = flt(frappe.db.get_value(
        "Purchase Invoice",
        {"docstatus": 1, "posting_date": ["between", [start, end]]},
        "sum(base_grand_total)") or 0)

    margin = income - headlease
    pct = (margin / income * 100) if income else 0

    # Per-building P&L straight off the Cost Centers.
    per_building = []
    for cc in frappe.get_all("Cost Center",
                             filters={"is_group": 0, "disabled": 0},
                             fields=["name", "cost_center_name"]):
        if cc.cost_center_name in ("Main", "Overhead / Admin"):
            continue
        inc = flt(frappe.db.get_value(
            "GL Entry",
            {"cost_center": cc.name, "is_cancelled": 0,
             "posting_date": ["between", [start, end]]},
            "sum(credit)") or 0)
        exp = flt(frappe.db.get_value(
            "GL Entry",
            {"cost_center": cc.name, "is_cancelled": 0,
             "posting_date": ["between", [start, end]]},
            "sum(debit)") or 0)
        if inc or exp:
            per_building.append([cc.cost_center_name,
                                 round(inc / 1000.0, 1), round(exp / 1000.0, 1)])

    # Forward PDC. Face value, then discounted for bounce history.
    pdc_rows, cheques = [], []
    if _has("PDC Cheque"):
        meta = frappe.get_meta("PDC Cheque")
        fields = ["name", "status"]
        for f in ("amount", "cheque_date", "tenant", "landlord", "direction"):
            if meta.has_field(f):
                fields.append(f)
        allc = frappe.get_all("PDC Cheque", fields=fields, limit=200)
        bounces = _bounces_by_customer()
        today = getdate(nowdate())
        horizons = {30: [0.0, 0.0], 60: [0.0, 0.0], 90: [0.0, 0.0]}
        for c in allc:
            amt = flt(c.get("amount"))
            cd = c.get("cheque_date")
            if not cd or not amt:
                continue
            d = (getdate(cd) - today).days
            if d < 0:
                continue
            for h in (30, 60, 90):
                if d <= h:
                    risk = BOUNCE_HAIRCUT if bounces.get(c.get("tenant")) else 0.0
                    horizons[h][0] += amt
                    horizons[h][1] += amt * (1 - risk)
                    break
        tot = [sum(v[0] for v in horizons.values()),
               sum(v[1] for v in horizons.values())]
        for h in (30, 60, 90):
            pdc_rows.append(["%d days" % h, "QAR " + _k(horizons[h][0]),
                             "QAR " + _k(horizons[h][1])])
        pdc_rows.append(["Total", "QAR " + _k(tot[0]), "QAR " + _k(tot[1])])

        for c in allc[:15]:
            cheques.append([
                c.get("tenant") or c.get("landlord") or c.name,
                "out" if c.get("direction") == "Outgoing" else "in",
                "QAR " + _k(c.get("amount")),
                _fmt(c.get("cheque_date"))[:6],
                c.get("status") or "Pending",
            ])

    # Owed to landlords: unpaid Purchase Invoices.
    pay = [[p.supplier, "QAR " + _k(p.outstanding_amount), _fmt(p.due_date)]
           for p in frappe.get_all(
               "Purchase Invoice",
               filters={"docstatus": 1, "outstanding_amount": [">", 0]},
               fields=["supplier", "outstanding_amount", "due_date"],
               order_by="due_date asc", limit=10)]

    return {
        "live": income > 0 or headlease > 0,
        "since": GENERATION_START,
        "pnl": {
            "income": "QAR " + _k(income),
            "hl": "QAR " + _k(headlease),
            "margin": "QAR " + _k(margin),
            "pct": "%.1f%%" % pct,
            "coll": ("QAR %s · %d%%" % (_k(collected), round(collected / income * 100))
                     if income else "—"),
            "comm": "QAR " + _k(0),
            "commP": "QAR " + _k(0),
        },
        "per_building": per_building,
        "receivables": _ageing_buckets(),
        "recv_detail": _recv_detail(),
        "pdc_forward": pdc_rows,
        "cheques": cheques,
        "pay_landlord": pay,
    }


def _recv_detail():
    cust = _customer_names()
    bounces = _bounces_by_customer()
    rows = []
    for c, e in sorted(_arrears_by_customer().items(),
                       key=lambda kv: -kv[1]["amount"])[:10]:
        lease = frappe.db.get_value(
            "Tenant Rental Agreement", {"tenant": c, "status": "Active"},
            ["building", "unit"], as_dict=True)
        loc = ("%s · %s" % (lease.building, lease.unit)) if lease else ""
        rows.append([
            cust.get(c, c), loc, "QAR " + _k(e["amount"]),
            _fmt(e["oldest"]), cint(bounces.get(c, 0)), "—",
        ])
    return rows


# ---------------------------------------------------------------- history

@frappe.whitelist()
def get_history():
    """The 12 months of manual books, for trend charts. Kept out of the GL
    on purpose: it is reference, not something to reconcile against."""
    _guard()
    if not _has("Historical Monthly PL"):
        return {"live": False, "months": [], "by_building": []}

    rows = frappe.get_all(
        "Historical Monthly PL",
        fields=["period_end", "period_label", "is_lump_period", "building",
                "rent_received", "owner_rent", "kahrama", "wifi", "profit"],
        order_by="period_end asc",
    )
    if not rows:
        return {"live": False, "months": [], "by_building": []}

    months, order = {}, []
    for r in rows:
        k = r.period_label
        if k not in months:
            months[k] = {"label": k, "end": str(r.period_end),
                         "lump": cint(r.is_lump_period),
                         "income": 0.0, "owner": 0.0, "profit": 0.0}
            order.append(k)
        m = months[k]
        m["income"] += flt(r.rent_received)
        m["owner"] += flt(r.owner_rent)
        m["profit"] += flt(r.profit)

    by_b = {}
    for r in rows:
        b = by_b.setdefault(r.building, {"income": 0.0, "owner": 0.0, "profit": 0.0})
        b["income"] += flt(r.rent_received)
        b["owner"] += flt(r.owner_rent)
        b["profit"] += flt(r.profit)

    return {
        "live": True,
        "months": [months[k] for k in order],
        "by_building": sorted(
            ([k, round(v["income"] / 1000.0, 1), round(v["owner"] / 1000.0, 1),
              round(v["profit"] / 1000.0, 1)] for k, v in by_b.items()),
            key=lambda r: -r[3]),
    }


# ------------------------------------------------------------ maintenance

@frappe.whitelist()
def get_maintenance():
    _guard()
    empty = {"live": False, "kpis": [0, 0, "—", 0],
             "requests": [], "by_building": []}
    if not _has("Maintenance Request"):
        return empty

    rows = frappe.get_all(
        "Maintenance Request",
        fields=["name", "building", "unit", "issue", "priority", "status",
                "reported_on", "resolved_on", "is_preventive"],
        order_by="reported_on desc", limit=100)
    if not rows:
        return dict(empty, live=True)

    now = frappe.utils.now_datetime()
    open_rows = [r for r in rows if r.status in ("Open", "In Progress", "Scheduled")]

    overdue = sum(1 for r in open_rows
                  if r.reported_on
                  and (now - frappe.utils.get_datetime(r.reported_on)).days > 3)

    done = [r for r in rows if r.status == "Resolved" and r.resolved_on and r.reported_on]
    avg = (sum((frappe.utils.get_datetime(r.resolved_on)
                - frappe.utils.get_datetime(r.reported_on)).total_seconds()
               for r in done) / len(done) / 86400) if done else 0

    prev = sum(1 for r in open_rows if r.is_preventive)

    def age(r):
        h = (now - frappe.utils.get_datetime(r.reported_on)).total_seconds() / 3600
        return ("%dh" % h) if h < 48 else ("%dd" % (h / 24))

    req = [[
        "%s · %s" % (r.building, r.unit or "—"), r.issue,
        r.priority, {"High": "red", "Medium": "orange", "Low": "blue"}.get(r.priority, "blue"),
        r.status, {"Open": "orange", "In Progress": "blue",
                   "Scheduled": "purple", "Resolved": "green"}.get(r.status, "blue"),
        age(r),
    ] for r in rows[:10]]

    cnt = {}
    for r in open_rows:
        cnt[r.building] = cnt.get(r.building, 0) + 1
    peak = max(cnt.values()) if cnt else 1
    cols = ["#BC512B", "#9A7A2E", "#9A7A2E", "#2E7D6A", "#2E7D6A"]
    by_b = [[b, str(n), "%d%%" % round(n / peak * 100), cols[min(i, 4)]]
            for i, (b, n) in enumerate(sorted(cnt.items(), key=lambda kv: -kv[1])[:5])]

    return {
        "live": True,
        "kpis": [len(open_rows), overdue, "%.1fd" % avg if done else "—", prev],
        "requests": req,
        "by_building": by_b,
    }


# ----------------------------------------------------------------- alerts

@frappe.whitelist()
def get_alerts():
    """The 6 surviving attention items, filtered against shared
    dismissals. Logic lives in darkbrown.api.attention; the entry shape
    is unchanged: [id, severity, icon, message, drill_route, label]."""
    from darkbrown.api import attention
    return attention.get_attention()


# -------------------------------------------------------------- approvals

@frappe.whitelist()
def get_approvals():
    """Draft documents waiting on a submit. Empty until invoices generate."""
    _guard()
    out = []

    for si in frappe.get_all("Sales Invoice", filters={"docstatus": 0},
                             fields=["name", "customer", "base_grand_total",
                                     "modified"],
                             order_by="modified desc", limit=5):
        out.append(["Sales Invoice", si.name, si.customer,
                    "QAR " + _k(si.base_grand_total),
                    frappe.utils.pretty_date(si.modified), "green", "invoice"])

    for pi in frappe.get_all("Purchase Invoice", filters={"docstatus": 0},
                             fields=["name", "supplier", "base_grand_total",
                                     "modified"],
                             order_by="modified desc", limit=5):
        out.append(["Landlord Invoice", pi.name, pi.supplier,
                    "QAR " + _k(pi.base_grand_total),
                    frappe.utils.pretty_date(pi.modified), "teal", "dollar"])

    return {"live": True, "approvals": out[:8], "count": len(out)}


# ------------------------------------------------------------------ combo

@frappe.whitelist()
def get_all():
    """One round trip instead of six. The frontend calls this."""
    _guard()
    return {
        "portfolio": get_portfolio(),
        "tenants": get_tenants(),
        "finance": get_finance(),
        "history": get_history(),
        "maintenance": get_maintenance(),
        "alerts": get_alerts(),
        "approvals": get_approvals(),
    }
