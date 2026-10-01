"""Read-only Accounts overview. Flows use a window; positions use its end date.

No imported receipt or cutover-control balance is treated as cash. Native
ERPNext ageing reconstructs outstanding at the reporting date, including
payments and credits, instead of reading today's invoice outstanding_amount.
"""
import datetime
import re
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate, today

from darkbrown.guards import ACC, GM, MD, guard
from darkbrown.permissions import allowed_buildings
from darkbrown.api import statements


def _access():
    guard(MD, GM, ACC)
    # Company bank balances and common costs cannot be partitioned by Building.
    # Never show company-wide figures to an explicitly building-scoped login.
    if allowed_buildings() is not None:
        frappe.throw("This company financial overview requires portfolio-wide access. "
                     "Use your assigned building records.", frappe.PermissionError)


def _window(start=None, end=None):
    now = getdate(today())
    start = start or str(now)[:7]
    end = end or str(now)[:7]
    if not all(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v or "") for v in (start, end)):
        frappe.throw("Choose valid starting and ending months.")
    frm = getdate(start + "-01")
    last = getdate(end + "-01")
    if frm > last or last > now.replace(day=1):
        frappe.throw("The starting month must precede the ending month; future months are unavailable.")
    months = (last.year - frm.year) * 12 + last.month - frm.month + 1
    if months > 120:
        frappe.throw("Choose a range of at most ten years.")
    nxt = (last.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return str(frm), str(min(now, nxt - datetime.timedelta(days=1)))


def _ageing(kind, as_on, company, cost_center=None):
    from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport
    filters = {"company": company, "report_date": as_on,
               "age_as_on": "Report Date", "ageing_based_on": "Due Date",
               "range": "30, 60, 90", "in_party_currency": 0,
               "show_future_payments": 0, "group_by_party": 0}
    if cost_center:
        filters["cost_center"] = [cost_center]
    result = ReceivablePayableReport(filters).run({
        "account_type": kind,
        "naming_by": ["Selling Settings", "cust_master_name"] if kind == "Receivable"
                     else ["Buying Settings", "supp_master_name"]})
    rows, buckets = [], dict.fromkeys(("current", "b30", "b60", "b90", "b90p"), 0.0)
    credits = 0.0
    for item in result[1]:
        r = dict(item)
        if not r.get("voucher_no"):
            continue
        amount = flt(r.get("outstanding"))
        if abs(amount) < 0.005:
            continue
        due = getdate(r.get("due_date") or r.get("posting_date"))
        age = (getdate(as_on) - due).days
        bucket = ("current" if age <= 0 else "b30" if age <= 30 else
                  "b60" if age <= 60 else "b90" if age <= 90 else "b90p")
        row = {"party": r.get("party_name") or r.get("customer_name") or
                        r.get("supplier_name") or r.get("party") or "",
               "party_id": r.get("party"), "voucher": r["voucher_no"],
               "voucher_type": r.get("voucher_type"), "due": str(due),
               "age": max(age, 0), "amount": round(amount, 2),
               "bucket": bucket, "cost_center": r.get("cost_center") or ""}
        rows.append(row)
        if amount > 0:
            buckets[bucket] += amount
        else:
            credits += amount
    buckets = {k: round(v, 2) for k, v in buckets.items()}
    rows.sort(key=lambda r: (-r["age"], r["party"], r["voucher"]))
    return {"rows": rows, "buckets": buckets,
            "gross": round(sum(buckets.values()), 2), "credits": round(credits, 2),
            "net": round(sum(r["amount"] for r in rows), 2), "as_on": as_on,
            "note": "Company-currency balances from ERPNext's dated payment ledger. "
                    "Positive balances are aged by due date; advances and credits are shown separately."}


def _performance(company, frm, to, nodes):
    # Aggregate in the database so volume never silently truncates GL lines.
    rows = frappe.get_all("GL Entry", filters={"company": company, "is_cancelled": 0,
        "posting_date": ["between", [frm, to]],
        "voucher_type": ["!=", statements.CLOSING_VOUCHER]},
        fields=["account", "cost_center", "posting_date", "sum(debit) as dr", "sum(credit) as cr"],
        group_by="account, cost_center, posting_date", limit=50001)
    if len(rows) > 50000:
        frappe.throw("Too many daily account groups; choose a shorter reporting range.")
    by_cc = {b.cost_center: b.name for b in frappe.get_all("Building",
             fields=["name", "cost_center"]) if b.cost_center}
    monthly, buildings = defaultdict(lambda: {"income": 0.0, "expense": 0.0}), defaultdict(
        lambda: {"income": 0.0, "expense": 0.0})
    for row in rows:
        node = nodes.get(row.account)
        if not node or node["cls"] not in ("Income", "Expense"):
            continue
        key = "income" if node["cls"] == "Income" else "expense"
        value = flt(row.cr) - flt(row.dr) if key == "income" else flt(row.dr) - flt(row.cr)
        month = str(row.posting_date)[:7]
        building = by_cc.get(row.cost_center, "Unassigned / company costs")
        monthly[month][key] += value
        buildings[building][key] += value
    month = getdate(frm).replace(day=1)
    while month <= getdate(to):
        monthly.setdefault(str(month)[:7], {"income": 0.0, "expense": 0.0})
        month = (month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    def pack(data, key):
        return [{key: label, "income": round(v["income"], 2), "expense": round(v["expense"], 2),
                 "net": round(v["income"] - v["expense"], 2),
                 "margin": round((v["income"] - v["expense"]) / v["income"] * 100, 1)
                           if v["income"] else None} for label, v in sorted(data.items())]
    return {"monthly": pack(monthly, "month"), "buildings": pack(buildings, "building")}


@frappe.whitelist()
def overview(start=None, end=None):
    guard(MD, GM, ACC)
    _access()
    frm, to = _window(start, end)
    company = statements._company()
    if not company:
        frappe.throw("Configure the reporting company before opening this overview.")
    nodes = statements._tree(company)
    sums = statements._sums(company, None, to)
    positions = []
    cash_accounts = statements._cash_accounts(nodes)
    for name, node in nodes.items():
        if node["group"]:
            continue
        kind = ("cash" if name in cash_accounts else "receivable" if node["type"] == "Receivable"
                else "payable" if node["type"] == "Payable" else "deposits"
                if node["cls"] == "Liability" and "deposit" in node["label"].lower() else None)
        if kind:
            dr, cr = sums.get(name, (0, 0))
            positions.append({"kind": kind, "code": node["code"], "label": node["label"],
                              "amount": round(dr - cr if node["nat"] == "Dr" else cr - dr, 2)})
    units = frappe.get_all("Unit", fields=["name", "building", "status"], limit=5001)
    if len(units) > 5000:
        frappe.throw("Unit register exceeds overview capacity.")
    occupied = sum(u.status == "Occupied" for u in units)
    pl = statements.profit_and_loss(frm=frm, to=to)
    performance = _performance(company, frm, to, nodes)
    # A missing account or incomplete aggregation must not become a plausible total.
    for key in ("income", "expense", "net"):
        if abs(sum(r[key] for r in performance["monthly"]) - pl[key]) > 0.05:
            frappe.throw("The monthly ledger breakdown does not reconcile to the P&L.")
    ar = _ageing("Receivable", to, company)
    ap = _ageing("Payable", to, company)
    notes = list(pl.get("notes", []))
    for kind, aged in (("receivable", ar), ("payable", ap)):
        control = round(sum(r["amount"] for r in positions if r["kind"] == kind), 2)
        aged["ledger_control"] = control
        aged["difference"] = round(control - aged["net"], 2)
        if abs(aged["difference"]) >= 0.01:
            notes.append("%s ageing differs from the general-ledger control by %.2f; "
                         "review unallocated or historical postings before relying on the ageing." %
                         (kind.title(), aged["difference"]))
    for item in (ar, ap):
        item["count"] = len(item["rows"])
        item["rows"] = item["rows"][:6]
    return {"frm": frm, "to": to, "company": company,
            "currency": frappe.db.get_value("Company", company, "default_currency"),
            "pl": pl, "cash_flow": statements.cash_flow(frm=frm, to=to),
            "balance_sheet": statements.balance_sheet(as_on=to),
            "positions": positions, **performance, "receivables": ar, "payables": ap,
            "occupancy": {"units": len(units), "occupied": occupied,
                "pct": round(occupied / len(units) * 100, 1) if units else None,
                "as_on": str(today()), "note": "Latest unit status; historical occupancy is not inferred. "
                    "Agreement review may be incomplete."}, "notes": notes}


@frappe.whitelist()
def ageing(kind="Receivable", start=None, end=None):
    guard(MD, GM, ACC)
    _access()
    if kind not in ("Receivable", "Payable"):
        frappe.throw("Unknown ageing report.")
    _frm, to = _window(start, end)
    return _ageing(kind, to, statements._company())
