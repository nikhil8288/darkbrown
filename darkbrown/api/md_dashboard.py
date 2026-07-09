"""Whitelisted read-only data methods for the MD dashboard.

PHASE 1 (live): Portfolio, Tenants & Leasing, and the occupancy/vacancy
KPI cards. Sourced entirely from Building / Unit / Tenant Rental Agreement /
Landlord Contract, all of which are populated.

PHASE 2 (stub): everything money-shaped. Rental income, head-lease cost,
margin, arrears ageing, PDC pipeline, liquidity. These come from Sales
Invoice + GL Entry + PDC Cheque and stay stubbed until July invoices post.
Each returns {"live": False} so the frontend can keep its mock arrays until
the data exists.

Every method re-checks the role server-side.

Shapes returned here match exactly what renderVals() already consumes.
Do not reshape on the client.
"""

import frappe
from frappe import _
from frappe.utils import getdate, add_days, nowdate, flt, cint

_ALLOWED = {"Managing Director", "System Manager", "Administrator"}

# Days before end_date at which an Active lease is treated as "on notice".
NOTICE_WINDOW = 60

# Days ahead we consider a lease "expiring soon".
EXPIRY_WINDOW = 90


def _guard():
    roles = set(frappe.get_roles(frappe.session.user))
    if not (roles & _ALLOWED):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _days_until(d):
    if not d:
        return None
    return (getdate(d) - getdate(nowdate())).days


# ---------------------------------------------------------------- helpers

def _active_leases():
    """Every Active tenant agreement, with the fields the dashboard needs."""
    return frappe.get_all(
        "Tenant Rental Agreement",
        filters={"status": "Active"},
        fields=[
            "name", "tenant", "building", "unit", "monthly_rent",
            "start_date", "end_date", "security_deposit",
        ],
    )


def _lease_by_unit():
    """unit name -> active lease dict. Last one wins if duplicated."""
    return {l.unit: l for l in _active_leases() if l.unit}


def _landlord_contracts():
    return frappe.get_all(
        "Landlord Contract",
        filters={"status": "Active"},
        fields=[
            "name", "landlord", "building", "total_owner_rent",
            "contract_start_date", "contract_end_date", "grace_period_days",
        ],
    )


def _unit_status(unit, lease):
    """Derive the four-state status the UI wants from the two we store."""
    if unit.occupancy_status == "Vacant":
        return "Vacant"
    if lease:
        d = _days_until(lease.end_date)
        if d is not None and 0 <= d <= NOTICE_WINDOW:
            return "Notice"
    return "Occupied"


# ---------------------------------------------------------------- portfolio

@frappe.whitelist()
def get_portfolio():
    """Feeds bRaw and unitMaster.

    Returns
        buildings: [name, income_M, headlease_M, total_units, vacant,
                    expiry, at_risk, leak_pct]
        units:     [bldg, unit, status, tenant, rent_K, vac_days,
                    furnish, type, move_out]
    """
    _guard()

    units = frappe.get_all(
        "Unit",
        fields=[
            "name", "unit_no", "unit_name", "building", "unit_type",
            "monthly_rent", "occupancy_status", "furnishing_status",
        ],
    )
    leases = _lease_by_unit()
    contracts = {c.building: c for c in _landlord_contracts()}

    tenant_names = {}
    for l in leases.values():
        if l.tenant and l.tenant not in tenant_names:
            tenant_names[l.tenant] = frappe.db.get_value(
                "Customer", l.tenant, "customer_name") or l.tenant

    unit_rows = []
    by_building = {}

    for u in units:
        lease = leases.get(u.name)
        status = _unit_status(u, lease)
        # Actual rent if let, asking rent if not.
        rent = flt(lease.monthly_rent) if lease else flt(u.monthly_rent)
        tenant = tenant_names.get(lease.tenant, "") if lease else ""
        if lease and not tenant:
            tenant = "(unlinked tenant)"
        move_out = ""
        if status == "Notice" and lease:
            move_out = frappe.utils.formatdate(lease.end_date, "dd MMM yyyy")

        unit_rows.append([
            u.building,
            u.unit_no or u.unit_name or u.name,
            status,
            tenant,
            round(rent / 1000.0, 1),   # QAR K, matches mock
            None,                       # vac_days: no vacant_since field yet
            u.furnishing_status or "",
            u.unit_type or "",
            move_out,
        ])

        b = by_building.setdefault(u.building, {
            "total": 0, "vacant": 0, "income": 0.0, "at_risk": 0,
        })
        b["total"] += 1
        if status == "Vacant":
            b["vacant"] += 1
        else:
            b["income"] += rent
        if status == "Notice":
            b["at_risk"] += 1

    building_rows = []
    for bname, agg in by_building.items():
        c = contracts.get(bname)
        headlease = flt(c.total_owner_rent) if c else 0.0
        expiry = (frappe.utils.formatdate(c.contract_end_date, "dd MMM yyyy")
                  if c and c.contract_end_date else "")

        # Rent leakage: how far below asking the let units actually achieve.
        asking = sum(
            flt(u.monthly_rent) for u in units
            if u.building == bname and u.occupancy_status == "Occupied"
        )
        leak = 0
        if asking > 0 and agg["income"] < asking:
            leak = int(round((1 - agg["income"] / asking) * 100))

        building_rows.append([
            bname,
            round(agg["income"] / 1000.0, 1),         # QAR K
            round(headlease / 1000.0, 1),             # QAR K
            agg["total"],
            agg["vacant"],
            expiry,
            agg["at_risk"],
            leak,
        ])

    building_rows.sort(key=lambda r: r[0])
    unit_rows.sort(key=lambda r: (r[0], r[1]))

    total_units = sum(b[3] for b in building_rows)
    total_vacant = sum(b[4] for b in building_rows)
    occ = ((total_units - total_vacant) / total_units * 100) if total_units else 0

    return {
        "live": True,
        "buildings": building_rows,
        "units": unit_rows,
        "strip": {
            "buildings": len(building_rows),
            "units": total_units,
            "vacant": total_vacant,
            "occupancy": round(occ, 1),
            # Bleed = head-lease carried on units earning nothing, QAR K.
            "bleed": round(sum(
                flt(contracts[b[0]].total_owner_rent) * (b[4] / b[3])
                for b in building_rows
                if b[0] in contracts and b[3]
            ) / 1000.0, 1),
        },
    }


# ------------------------------------------------------------------ tenants

@frappe.whitelist()
def get_tenants():
    """Feeds tnRaw, agExpiring, agOther, churnNotice, tnStrip.

    Arrears and bounce counts are zero until Sales Invoice and PDC Cheque
    carry data; the shape stays identical so nothing on the client changes.
    """
    _guard()

    agreements = frappe.get_all(
        "Tenant Rental Agreement",
        fields=[
            "name", "tenant", "building", "unit", "monthly_rent",
            "status", "start_date", "end_date",
        ],
        order_by="end_date asc",
    )

    cust = {
        c.name: c.customer_name
        for c in frappe.get_all("Customer", fields=["name", "customer_name"])
    }

    tn_rows, expiring, other, notice = [], [], [], []
    active = expiring_soon = 0

    unit_no = {
        u.name: (u.unit_no or u.unit_name or u.name)
        for u in frappe.get_all("Unit", fields=["name", "unit_no", "unit_name"])
    }

    for a in agreements:
        # Orphan agreement: Customer link is null or deleted. Skip it.
        name = cust.get(a.tenant)
        if not name:
            continue
        loc = "%s · %s" % (a.building or "", unit_no.get(a.unit, a.unit or ""))
        days = _days_until(a.end_date)

        if a.status == "Active":
            active += 1
            if days is not None and 0 <= days <= EXPIRY_WINDOW:
                expiring_soon += 1
                agreement_state = "Expiring"
                col = "red" if days <= 30 else "orange"
                expiring.append([
                    name, loc,
                    frappe.utils.formatdate(a.end_date, "dd MMM yyyy"),
                    "%d days" % days, col,
                ])
                notice.append([
                    name, loc,
                    frappe.utils.formatdate(a.end_date, "dd MMM yyyy"),
                    "Non-renewal",
                ])
            else:
                agreement_state = "Active"
        elif a.status == "Expired":
            agreement_state = "Lapsed"
            other.append([name, "Lapsed · no current contract", "red"])
        elif a.status == "Terminated":
            continue
        else:
            agreement_state = "Active"

        tn_rows.append([
            name,
            loc,
            round(flt(a.monthly_rent) / 1000.0, 1),   # QAR K
            agreement_state,
            "current",     # standing — arrears unknown until invoices exist
            0.0,           # outstanding
            0,             # bounce count
            frappe.utils.formatdate(a.start_date, "MMM yyyy") if a.start_date else "",
            0.0,           # lifetime collected
        ])

    return {
        "live": True,
        "tenants": tn_rows,
        "expiring": expiring[:10],
        "other": other[:10],
        "notice": notice[:10],
        "strip": {
            "active": active,
            "expiring": expiring_soon,
            "arrears": 0,       # phase 2
            "lapsed": len(other),
            "notice": len(notice),
        },
    }


# ----------------------------------------------------------------- overview

@frappe.whitelist()
def get_overview(timeframe="month"):
    """Only the cards that have real data. Money cards stay stubbed.

    Returns occupancy, vacant_units, expiring_contracts. The frontend keeps
    its mock values for the six money cards until get_finance goes live.
    """
    _guard()

    pf = get_portfolio()
    tn = get_tenants()

    return {
        "live": True,
        "occupancy": pf["strip"]["occupancy"],
        "units_total": pf["strip"]["units"],
        "units_let": pf["strip"]["units"] - pf["strip"]["vacant"],
        "vacant": pf["strip"]["vacant"],
        "bleed_month": pf["strip"]["bleed"],
        "expiring": tn["strip"]["expiring"],
        "per_building": pf["buildings"],
        # Money cards deliberately absent — client falls back to mock.
        "finance_live": False,
    }


# ------------------------------------------------------------------ stubs

@frappe.whitelist()
def get_finance(timeframe="month"):
    """Stub. Goes live once Sales Invoices exist from 1-Jul-2026."""
    _guard()
    return {"live": False, "reason": "No invoices posted before 2026-07-01"}


@frappe.whitelist()
def get_maintenance():
    """Stub. No Maintenance Request DocType yet."""
    _guard()
    return {"live": False, "reason": "Maintenance DocType not built"}
