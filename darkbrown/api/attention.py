"""Attention system for the MD dashboard.

Six surviving attention items (spec numbering preserved):
    1  Arrears                  get_arrears()      #tenants/arrears
    2  Landlord PDC due <=15d   get_landlord_pdc() detail + shared resolve
    6  Vacant units             get_vacant()       #portfolio/units/Vacant
    9  Head-lease expiring 90d  get_headlease_expiring()
    10 Tenant agmt expiring 30d get_tenant_expiring()
    13 Maintenance aged >48h    get_maintenance_aging()

get_attention() emits the alert strip (replaces the old get_alerts body),
filtered against MD Alert Dismissal (shared "resolve for everyone").

Read-only by design: workflows come later. Every method returns a stable
shape when empty. Role is re-checked server-side on every call.
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, now_datetime, flt, cint, formatdate

from darkbrown.api.md_dashboard import (
    _guard, _has, _days_until, _fmt, _customer_names, _unit_labels,
    _landlord_contracts,
)

# ---------------------------------------------------------------- config

# PDC Cheque live-site fields (confirmed from Customize Form 12-Jul-2026):
# direction, party, tenant_rental_agreement, landlord_contract,
# cheque_number, bank_name, cheque_date, amount, status, cleared_date.
# The outgoing option value is auto-detected from the Select options
# (first value containing "out"/"landlord"/"pay"); set PDC_OUTGOING_VALUE
# explicitly to override if detection picks wrong.
PDC_DIRECTION_FIELD = "direction"
PDC_OUTGOING_VALUE = None           # None = auto-detect from field options
PDC_MATURITY_FIELD = "cheque_date"
PDC_WINDOW_DAYS = 15


def _pdc_outgoing_value():
    if PDC_OUTGOING_VALUE:
        return PDC_OUTGOING_VALUE
    if not (_has("PDC Cheque")
            and frappe.get_meta("PDC Cheque").has_field(PDC_DIRECTION_FIELD)):
        return None
    opts = (frappe.get_meta("PDC Cheque")
            .get_field(PDC_DIRECTION_FIELD).options or "")
    for o in [x.strip() for x in opts.split("\n") if x.strip()]:
        low = o.lower()
        if "out" in low or "landlord" in low or "pay" in low:
            return o
    return None

MAINT_AGE_HOURS = 48
HEADLEASE_WINDOW = 90
TENANT_WINDOW = 30

_BUCKETS = [(30, "0-30", "amber"), (60, "31-60", "orange"),
            (90, "61-90", "red"), (10 ** 6, "90+", "dark")]


def _bucket(days):
    for limit, label, band in _BUCKETS:
        if days <= limit:
            return label, band
    return "90+", "dark"


def _grace_by_building():
    """building -> grace_period_days from its Active Landlord Contract."""
    return {c.building: cint(c.grace_period_days)
            for c in _landlord_contracts() if c.building}


# ------------------------------------------------------- 1. arrears view

@frappe.whitelist()
def get_arrears():
    """Per-unit arrears rows, worst-first. Once Collection Cases exist a
    row carries the case status + latest timeline note; overdue-but-
    pre-grace rows show as flagged rows without a case."""
    _guard()
    today = getdate(nowdate())

    inv = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["name", "customer", "outstanding_amount", "due_date",
                "grand_total"],
    )
    by_cust = {}
    for r in inv:
        by_cust.setdefault(r.customer, []).append(r)
    if not by_cust:
        return {"live": True, "rows": [], "total": 0.0, "count": 0}

    leases = frappe.get_all(
        "Tenant Rental Agreement",
        filters={"tenant": ["in", list(by_cust)],
                 "status": ["in", ["Active", "Expired"]]},
        fields=["name", "tenant", "building", "unit", "monthly_rent",
                "status", "start_date", "end_date", "security_deposit"],
    )
    lease_by_tenant = {}
    for l in leases:  # prefer Active when a tenant has both
        cur = lease_by_tenant.get(l.tenant)
        if cur is None or (cur.status != "Active" and l.status == "Active"):
            lease_by_tenant[l.tenant] = l

    cust_meta = {c.name: c for c in frappe.get_all(
        "Customer", filters={"name": ["in", list(by_cust)]},
        fields=["name", "customer_name", "customer_type",
                "mobile_no", "email_id"])}
    ulab = _unit_labels()
    grace = _grace_by_building()
    cases = _cases_by_tenant()

    rows, total = [], 0.0
    for tenant, invoices in by_cust.items():
        cm = cust_meta.get(tenant)
        lease = lease_by_tenant.get(tenant)
        outstanding = sum(flt(i.outstanding_amount) for i in invoices)
        total += outstanding

        oldest = min((getdate(i.due_date) for i in invoices if i.due_date),
                     default=None)
        oldest_days = (today - oldest).days if oldest else 0
        label, band = _bucket(oldest_days)

        rent = flt(lease.monthly_rent) if lease else 0.0
        months_behind = round(outstanding / rent, 1) if rent else None
        deposit = flt(lease.security_deposit) if lease else 0.0

        g = grace.get(lease.building) if lease else None
        past_grace = bool(g is not None and oldest_days > g)

        case = cases.get(tenant, {})

        rows.append({
            "building": lease.building if lease else "",
            "unit": ulab.get(lease.unit, lease.unit) if lease else "",
            "tenant": cm.customer_name if cm else tenant,
            "tenant_type": cm.customer_type if cm else "",
            "mobile": (cm.mobile_no or "") if cm else "",
            "email": (cm.email_id or "") if cm else "",
            "monthly_rent": rent,
            "outstanding": outstanding,
            "months_behind": months_behind,
            "invoice_count": len(invoices),
            "oldest_overdue_days": oldest_days,
            "aging_bucket": label, "aging_band": band,
            "lease": lease.name if lease else "",
            "lease_status": lease.status if lease else "No lease",
            "lease_start": _fmt(lease.start_date) if lease else "",
            "lease_end": _fmt(lease.end_date) if lease else "",
            "deposit_held": deposit,
            "deposit_gap": max(0.0, outstanding - deposit),
            "past_grace": past_grace,
            "case": case.get("name", ""),
            "case_status": case.get("status", ""),
            "latest_note": case.get("note", ""),
            "update": "",  # workflow deferred per spec
            "invoices": [{
                "invoice": i.name,
                "outstanding": flt(i.outstanding_amount),
                "due_date": _fmt(i.due_date),
                "days_overdue": max(0, (today - getdate(i.due_date)).days)
                if i.due_date else 0,
            } for i in sorted(invoices, key=lambda x: x.due_date or today)],
        })

    rows.sort(key=lambda r: r["outstanding"], reverse=True)
    return {"live": True, "rows": rows, "total": total, "count": len(rows)}


def _cases_by_tenant():
    """Open Collection Cases keyed by tenant, with latest timeline note."""
    if not _has("Collection Case"):
        return {}
    cases = frappe.get_all(
        "Collection Case",
        filters={"status": ["not in", ["Collected"]]},
        fields=["name", "tenant", "status"],
    )
    out = {}
    for c in cases:
        note = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Collection Case",
                     "reference_name": c.name, "comment_type": "Comment"},
            fields=["content"], order_by="creation desc", limit=1)
        out[c.tenant] = {
            "name": c.name, "status": c.status,
            "note": frappe.utils.strip_html(note[0].content) if note else "",
        }
    return out


# ------------------------------------------ 2. landlord PDC due (15 days)

def _pdc_configured():
    return bool(_pdc_outgoing_value())


@frappe.whitelist()
def get_landlord_pdc():
    """Outgoing cheques maturing within PDC_WINDOW_DAYS."""
    _guard()
    if not _pdc_configured():
        return {"live": True, "configured": False, "rows": []}

    meta = frappe.get_meta("PDC Cheque")
    fields = ["name", PDC_MATURITY_FIELD, PDC_DIRECTION_FIELD]
    for f in ("amount", "bank_name", "party", "landlord_contract",
              "cheque_number", "status"):
        if meta.has_field(f):
            fields.append(f)

    today = getdate(nowdate())
    hl_building = {c.name: c.building for c in frappe.get_all(
        "Landlord Contract", fields=["name", "building"])}
    rows = []
    for c in frappe.get_all("PDC Cheque",
                            filters={PDC_DIRECTION_FIELD: _pdc_outgoing_value()},
                            fields=fields):
        md = c.get(PDC_MATURITY_FIELD)
        if not md:
            continue
        d = (getdate(md) - today).days
        if 0 <= d <= PDC_WINDOW_DAYS:
            rows.append({
                "cheque": c.name,
                "cheque_no": c.get("cheque_number", ""),
                "bank": c.get("bank_name", ""),
                "amount": flt(c.get("amount")),
                "landlord": c.get("party", ""),
                "building": hl_building.get(c.get("landlord_contract"), ""),
                "maturity": _fmt(md),
                "days_remaining": d,
            })
    rows.sort(key=lambda r: r["days_remaining"])
    return {"live": True, "configured": True, "rows": rows}


@frappe.whitelist()
def resolve_alert(alert_id):
    """Shared, persisted dismissal — gone for everyone (attention item 2's
    Resolve; distinct from the GM bell's per-user native dismiss)."""
    _guard()
    if not frappe.db.exists("MD Alert Dismissal", alert_id):
        frappe.get_doc({
            "doctype": "MD Alert Dismissal",
            "alert_id": alert_id,
            "dismissed_by": frappe.session.user,
            "dismissed_on": now_datetime(),
        }).insert(ignore_permissions=False)
    return {"ok": True}


def _dismissed():
    if not _has("MD Alert Dismissal"):
        return set()
    return {d.name for d in frappe.get_all("MD Alert Dismissal")}


# ------------------------------------------------------- 6. vacant units

@frappe.whitelist()
def get_vacant():
    _guard()
    today = getdate(nowdate())
    units = frappe.get_all(
        "Unit",
        filters={"occupancy_status": "Vacant"},
        fields=["name", "unit_no", "unit_name", "building", "unit_type",
                "furnishing_status"] if frappe.get_meta("Unit").has_field(
            "furnishing_status") else
        ["name", "unit_no", "unit_name", "building", "unit_type"],
    )
    if not units:
        return {"live": True, "rows": [], "count": 0, "bleed_total": 0.0}

    contracts = {c.building: c for c in _landlord_contracts()}
    unit_count = {}
    for u in frappe.get_all("Unit", fields=["building"]):
        unit_count[u.building] = unit_count.get(u.building, 0) + 1

    # last lease per vacant unit -> last tenant + days vacant
    prior = frappe.get_all(
        "Tenant Rental Agreement",
        filters={"unit": ["in", [u.name for u in units]],
                 "status": ["in", ["Expired", "Terminated"]]},
        fields=["unit", "tenant", "end_date"],
        order_by="end_date desc",
    )
    last = {}
    for p in prior:
        last.setdefault(p.unit, p)   # first hit = most recent
    cust = _customer_names()

    rows, bleed_total = [], 0.0
    for u in units:
        c = contracts.get(u.building)
        n = unit_count.get(u.building, 0) or 1
        bleed = flt(c.total_owner_rent) / n if c else 0.0
        bleed_total += bleed
        lp = last.get(u.name)
        rows.append({
            "building": u.building,
            "unit": u.unit_no or u.unit_name or u.name,
            "unit_type": u.get("unit_type", ""),
            "furnishing": u.get("furnishing_status", ""),
            "bleed": round(bleed, 0),
            "asking_rent": None,   # no asking-rent field on Unit yet
            "last_tenant": cust.get(lp.tenant, lp.tenant) if lp else "—",
            "days_vacant": (today - getdate(lp.end_date)).days
            if lp and lp.end_date else None,
        })
    rows.sort(key=lambda r: (r["days_vacant"] is None, -(r["days_vacant"] or 0)))
    return {"live": True, "rows": rows, "count": len(rows),
            "bleed_total": round(bleed_total, 0)}


# --------------------------------------- 9. head-lease expiring (90 days)

@frappe.whitelist()
def get_headlease_expiring():
    _guard()
    rows = []
    for c in _landlord_contracts():
        d = _days_until(c.contract_end_date)
        if d is None or not (0 <= d <= HEADLEASE_WINDOW):
            continue
        units = frappe.db.count("Unit", {"building": c.building})
        at_risk = frappe.db.count(
            "Tenant Rental Agreement",
            {"building": c.building, "status": "Active"})
        rows.append({
            "building": c.building,
            "landlord": c.landlord,
            "contract": c.name,
            "start": _fmt(c.contract_start_date),
            "end": _fmt(c.contract_end_date),
            "days_remaining": d,
            "urgency": "red" if d <= 30 else ("orange" if d <= 60 else "amber"),
            "monthly_cost": flt(c.total_owner_rent),
            "units": units,
            "tenancies_at_risk": at_risk,
        })
    rows.sort(key=lambda r: r["days_remaining"])
    return {"live": True, "rows": rows, "count": len(rows)}


# ------------------------------------ 10. tenant agreements expiring 30d

@frappe.whitelist()
def get_tenant_expiring():
    _guard()
    arrears_tenants = {r.customer for r in frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1, "outstanding_amount": [">", 0]},
        fields=["customer"])}
    cust = _customer_names()
    ulab = _unit_labels()

    rows = []
    for a in frappe.get_all(
            "Tenant Rental Agreement", filters={"status": "Active"},
            fields=["name", "tenant", "building", "unit", "monthly_rent",
                    "start_date", "end_date", "security_deposit"]):
        d = _days_until(a.end_date)
        if d is None or not (0 <= d <= TENANT_WINDOW):
            continue
        rows.append({
            "tenant": cust.get(a.tenant, a.tenant),
            "building": a.building,
            "unit": ulab.get(a.unit, a.unit),
            "agreement": a.name,
            "start": _fmt(a.start_date),
            "end": _fmt(a.end_date),
            "days_remaining": d,
            "urgency": "red" if d <= 7 else ("orange" if d <= 15 else "amber"),
            "monthly_rent": flt(a.monthly_rent),
            "deposit_held": flt(a.security_deposit),
            "in_arrears": a.tenant in arrears_tenants,
        })
    rows.sort(key=lambda r: r["days_remaining"])
    return {"live": True, "rows": rows, "count": len(rows)}


# ------------------------------------------ 13. maintenance aged > 48 h

@frappe.whitelist()
def get_maintenance_aging():
    _guard()
    if not _has("Maintenance Request"):
        return {"live": True, "rows": [], "count": 0}
    now = now_datetime()
    rows = []
    for m in frappe.get_all(
            "Maintenance Request",
            filters={"status": ["in", ["Open", "In Progress"]]},
            fields=["name", "building", "unit", "issue", "priority",
                    "status", "reported_on", "assigned_to", "creation"]):
        age_h = (now - m.creation).total_seconds() / 3600.0
        if age_h <= MAINT_AGE_HOURS:
            continue
        rows.append({
            "request": m.name,
            "building": m.building,
            "unit": m.unit or "",
            "issue": m.issue,
            "priority": m.priority,
            "status": m.status,
            "hours_past": round(age_h - MAINT_AGE_HOURS),
            "reported": _fmt(m.reported_on),
            "assigned_to": m.assigned_to or "—",
        })
    rows.sort(key=lambda r: r["hours_past"], reverse=True)
    return {"live": True, "rows": rows, "count": len(rows)}


# --------------------------------------------------- alert strip (6 max)

@frappe.whitelist()
def get_attention():
    """The 6 surviving alerts, each pointing at its detail route.
    Entry shape kept identical to the old get_alerts():
    [id, severity, icon, message, drill_route, drill_label]."""
    _guard()
    gone = _dismissed()
    out = []

    ar = get_arrears()
    if ar["count"]:
        out.append(["arrears", "high", "invoice",
                    "Arrears — QAR %s across %d tenants"
                    % ("{:,.0f}".format(ar["total"]), ar["count"]),
                    "tenants/arrears", "Open arrears"])

    if _pdc_configured():
        for r in get_landlord_pdc()["rows"]:
            aid = "pdc_%s" % r["cheque"]
            if aid in gone:
                continue
            out.append([aid, "high", "dollar",
                        "Landlord cheque %s — QAR %s to %s in %d days"
                        % (r["cheque_no"] or r["cheque"],
                           "{:,.0f}".format(r["amount"]),
                           r["landlord"], r["days_remaining"]),
                        "finance/pdc", "Cheque detail"])

    vc = get_vacant()
    if vc["count"]:
        out.append(["vac", "warn", "home",
                    "%d vacant units · QAR %s/mo head-lease bleed"
                    % (vc["count"], "{:,.0f}".format(vc["bleed_total"])),
                    "portfolio/units/Vacant", "Vacant units"])

    hl = get_headlease_expiring()
    if hl["count"]:
        out.append(["hl", "warn", "building",
                    "%d head-lease%s expiring within %d days"
                    % (hl["count"], "" if hl["count"] == 1 else "s",
                       HEADLEASE_WINDOW),
                    "portfolio/headleases", "Review head-leases"])

    te = get_tenant_expiring()
    if te["count"]:
        out.append(["exp", "warn", "calendar",
                    "%d tenant agreement%s expire within %d days"
                    % (te["count"], "" if te["count"] == 1 else "s",
                       TENANT_WINDOW),
                    "tenants/expiring", "Review renewals"])

    mn = get_maintenance_aging()
    if mn["count"]:
        out.append(["mnt", "warn", "wrench",
                    "%d maintenance request%s open past %dh"
                    % (mn["count"], "" if mn["count"] == 1 else "s",
                       MAINT_AGE_HOURS),
                    "maintenance/aging", "Aged tickets"])

    return {"live": True,
            "alerts": [a for a in out if a[0] not in gone][:6]}
