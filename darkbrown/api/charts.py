"""Forward-looking finance charts for the MD dashboard.

get_projection() feeds the Finance > Projection sub-view:

  C1  12-month forward cash flow — expected inflow vs committed head-lease
      outflow, net per month, and a running cumulative line. First month
      the running line goes negative = the danger month.
  C2  committed vs at-risk inflow — same 12 months, splitting expected
      rent into "committed" (lease contractually covers the month) vs
      "assumed" (lease expires first; counts only if renewed), plus
      incoming PDC cover per month where the direction field exists.
  C8  collected vs billed per month since GENERATION_START — Sales
      Invoice billed vs Payment Entry receipts.

Modelling choices (deliberate, keep in sync with the spec):
  - Monthly granularity, no intra-month proration.
  - A tenant lease is "committed" for months its end_date covers;
    afterwards its rent moves to "assumed" (renewal risk). C1's inflow
    = committed + assumed (the realistic-if-renewals-hold view).
  - Head-lease cost continues at the same rate past contract end
    (renewal assumed — conservative on cash), with the expiry flagged.
  - Grace months are skipped on the outflow side, same rule as the
    invoicer: skipped while contract_start + rent_free_days covers
    the whole month.

C4 (spread trend) intentionally has no endpoint — the frontend renders
it straight from get_history(), which already aggregates the imported
Jul-2025 → Jun-2026 books.
"""

import frappe
from frappe.utils import (getdate, nowdate, get_first_day, get_last_day,
                          add_months, add_days, flt, cint)

from darkbrown.api.attention import _guard, _has
from darkbrown.utils.rent_invoicing import GENERATION_START

HORIZON = 12


def _months(n, anchor=None):
    d = get_first_day(getdate(anchor or nowdate()))
    out = []
    for i in range(n):
        s = add_months(d, i)
        out.append((s, get_last_day(s), s.strftime("%b %y")))
    return out


@frappe.whitelist()
def get_projection():
    _guard()
    months = _months(HORIZON)

    leases = frappe.get_all(
        "Tenancy Agreement", filters={"status": ["in", ["Active", "Expiring"]]},
        fields=["monthly_rent", "start_date", "end_date"])
    contracts = frappe.get_all(
        "Head Lease", filters={"status": "Active"},
        fields=["building", "monthly_rent", "start_date",
                "end_date", "rent_free_days"])

    pdc_field = None
    if _has("Cheque"):
        meta = frappe.get_meta("Cheque")
        if meta.has_field("direction") and meta.has_field("cheque_date"):
            pdc_field = "direction"
    cheques = frappe.get_all(
        "Cheque", fields=["amount", "cheque_date", "direction"]
    ) if pdc_field else []

    floor = 0.0
    if _has("DBR Settings"):
        floor = flt(frappe.db.get_single_value("DBR Settings",
                                               "minimum_cash_floor") or 0)

    # Overhead was missing from this projection entirely, which mattered more
    # here than anywhere else: the whole point of C1 is finding the month the
    # cumulative line goes under, and a fixed monthly outflow left out of it
    # pushes that month later than it really is. Payroll is taken as it stands
    # today; petty cash as a trailing average, because a one-off last March
    # says nothing about next March (D80).
    from darkbrown.api.people import monthly_staff_cost
    from darkbrown.api.pettycash import monthly_spend_average
    payroll = monthly_staff_cost()
    petty_avg = monthly_spend_average(3)
    overhead = payroll + petty_avg

    rows, running = [], 0.0
    danger, hl_expiring = None, []
    for (ms, me, label) in months:
        committed = assumed = 0.0
        for l in leases:
            rent = flt(l.monthly_rent)
            if rent <= 0 or (l.start_date and getdate(l.start_date) > me):
                continue
            if l.end_date and getdate(l.end_date) < ms:
                assumed += rent          # expired by then; renewal risk
            else:
                committed += rent        # contract covers this month

        outflow = 0.0
        for c in contracts:
            amt = flt(c.monthly_rent)
            if amt <= 0 or (c.start_date
                            and getdate(c.start_date) > me):
                continue
            g = cint(c.rent_free_days)
            if g and c.start_date and \
                    getdate(add_days(c.start_date, g)) >= me:
                continue                 # whole month inside grace
            outflow += amt               # continues past end: renewal assumed
            if c.end_date and ms <= getdate(c.end_date) <= me:
                hl_expiring.append("%s (%s)" % (c.building, label))

        pdc_in = sum(flt(q.amount) for q in cheques
                     if q.cheque_date and ms <= getdate(q.cheque_date) <= me
                     and (q.direction or "") != "Outgoing")

        outflow += overhead

        inflow = committed + assumed
        net = inflow - outflow
        running += net
        if danger is None and running < floor:
            danger = label
        rows.append({"label": label,
                     "committed": round(committed), "assumed": round(assumed),
                     "inflow": round(inflow), "outflow": round(outflow),
                     "net": round(net), "running": round(running),
                     "pdc_in": round(pdc_in),
                     "overhead": round(overhead)})

    return {"live": True, "months": rows, "danger": danger,
            "floor": floor, "hl_expiring": hl_expiring,
            "payroll": round(payroll), "pettyAvg": round(petty_avg),
            "pdc": bool(pdc_field), "c8": _collected_vs_billed(),
            "scenarios": _scenarios()}


def _scenarios():
    if not _has("Building Scenario"):
        return []
    return frappe.get_all(
        "Building Scenario",
        fields=["name", "scenario_label", "headlease_monthly", "units",
                "avg_unit_rent", "grace_months", "ramp_months"],
        order_by="modified desc", limit=10)


@frappe.whitelist()
def save_scenario(label, headlease_monthly=0, units=0, avg_unit_rent=0,
                  grace_months=0, ramp_months=0):
    """F1: persist a what-if scenario. Upserts by label."""
    _guard()
    label = (label or "").strip()
    if not label:
        frappe.throw("Scenario needs a label")
    vals = dict(headlease_monthly=flt(headlease_monthly), units=cint(units),
                avg_unit_rent=flt(avg_unit_rent),
                grace_months=cint(grace_months), ramp_months=cint(ramp_months))
    if frappe.db.exists("Building Scenario", label):
        doc = frappe.get_doc("Building Scenario", label)
        doc.update(vals)
        doc.save()
    else:
        frappe.get_doc(dict(doctype="Building Scenario",
                            scenario_label=label, **vals)).insert()
    return {"ok": True, "scenarios": _scenarios()}


@frappe.whitelist()
def set_cash_floor(value):
    """F2: owner-set minimum cash floor (whole company, QAR)."""
    _guard()
    doc = frappe.get_doc("DBR Settings")
    doc.minimum_cash_floor = flt(value)
    doc.save()
    return {"ok": True, "floor": flt(value)}


def _collected_vs_billed():
    start = get_first_day(getdate(GENERATION_START))
    today = getdate(nowdate())
    out = []
    s = start
    while s <= today and len(out) < 12:
        e = get_last_day(s)
        billed = flt(frappe.db.get_value(
            "Sales Invoice",
            {"docstatus": 1, "posting_date": ["between", [s, e]]},
            "sum(base_grand_total)") or 0)
        collected = flt(frappe.db.get_value(
            "Payment Entry",
            {"docstatus": 1, "payment_type": "Receive",
             "posting_date": ["between", [s, e]]},
            "sum(paid_amount)") or 0)
        out.append({"label": s.strftime("%b %y"),
                    "billed": round(billed), "collected": round(collected)})
        s = add_months(s, 1)
    return out
