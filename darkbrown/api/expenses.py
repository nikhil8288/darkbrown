"""Recording what the business spends, and saying where it lands.

Two things the ledger could not answer before this module existed. The first is
trivial and was the blocker: there was no way to enter an expense at all.
Everything on the cost side arrived through the historical cutover journal, so
from go-live the only spend the system could see was head-lease rent.

The second is the one that matters. Every expense head is either a building's
or the company's, and until now nothing recorded which. That meant a per-
building P&L that showed head-lease rent and nothing else, and a company P&L
that was one undifferentiated list. `utils.chart_of_accounts` holds the
mapping; this module writes against it and reads back out of it.

The screens go through here rather than through the desk because the desk form
would happily let someone put a salary on one building.
"""

import json

import frappe
from frappe.utils import add_months, flt, get_first_day, getdate, today

from darkbrown.guards import ACC, GM, MD, guard
from darkbrown.utils import allocation
from darkbrown.utils.chart_of_accounts import (BUILDING, COMMON, GROUPS,
                                               HEADS, basis_of, ensure_chart,
                                               group_of)

#: Ceiling on one read of the register.
REGISTER_CAP = 500


def _payload(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload or {}


def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or (frappe.get_all("Company", limit=1) or [{}])[0].get("name"))


# ------------------------------------------------------------------- the form

@frappe.whitelist()
def heads():
    """Every expense head the entry screen may offer, with its group and basis.

    Accounts missing from the chart are reported rather than hidden, because a
    head that is not there is why an expense cannot be keyed, and a dropdown
    that silently omits it turns a five-second fix into an afternoon.
    """
    guard(MD, GM, ACC)
    company = _company()
    existing = {a.account_name: a.name for a in frappe.get_all(
        "Account", filters={"company": company, "root_type": "Expense",
                            "is_group": 0},
        fields=["name", "account_name"], limit=1000)}

    out, missing = [], []
    for head, group, basis in HEADS:
        acc = existing.get(head)
        if not acc:
            missing.append(head)
            continue
        out.append({"head": head, "account": acc, "group": group,
                    "basis": basis})

    return {
        "heads": out,
        "groups": [{"key": g, "label": label} for g, label in GROUPS],
        "missing": missing,
        "banks": [a.name for a in frappe.get_all(
            "Account", filters={"company": company, "is_group": 0,
                                "account_type": ["in", ("Bank", "Cash")]},
            fields=["name"], order_by="account_name", limit=100)],
        "buildings": [{"id": b.name, "label": b.building_name or b.name,
                       "status": b.status}
                      for b in frappe.get_all(
                          "Building", fields=["name", "building_name",
                                              "status"],
                          order_by="building_name", limit=500)],
        "suppliers": [s.name for s in frappe.get_all(
            "Supplier", fields=["name"], order_by="name", limit=500)],
    }


@frappe.whitelist()
def record(payload):
    """Key one expense and post it. Accounts and the GM; not Maintenance."""
    guard(MD, GM, ACC)
    d = _payload(payload)

    head = d.get("head") or d.get("expense_head")
    if not head:
        frappe.throw("An expense needs a head.")
    if not basis_of(head):
        frappe.throw("%s is not one of the expense heads on the chart." % head)

    doc = frappe.get_doc({
        "doctype": "Expense Entry",
        "expense_date": d.get("date") or today(),
        "expense_head": head,
        "amount": flt(d.get("amount")),
        "building": d.get("building") or None,
        "payment_mode": d.get("mode") or "Bank",
        "paid_from": d.get("paid_from") or None,
        "supplier": d.get("supplier") or None,
        "reference": d.get("ref") or None,
        "description": d.get("what") or d.get("description"),
        "notes": d.get("notes") or None,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()

    return {"id": doc.name, "basis": doc.basis,
            "cost_center": doc.cost_center,
            "journal": doc.journal_entry,
            "building": doc.building,
            "amount": flt(doc.amount)}


# --------------------------------------------------------------- the register

@frappe.whitelist()
def register(frm=None, to=None, basis=None, building=None, limit=None):
    """Expenses in a window, with the totals the screen puts in its boxes."""
    guard(MD, GM, ACC)
    to = str(getdate(to or today()))
    frm = str(getdate(frm or get_first_day(add_months(getdate(to), -11))))

    filters = {"docstatus": 1, "expense_date": ["between", [frm, to]]}
    if basis:
        filters["basis"] = basis
    if building:
        filters["building"] = building

    rows = frappe.get_all(
        "Expense Entry", filters=filters,
        fields=["name", "expense_date", "expense_head", "amount", "basis",
                "building", "payment_mode", "supplier", "paid_from",
                "reference", "description", "journal_entry"],
        order_by="expense_date desc, name desc",
        limit=int(limit or REGISTER_CAP))

    names = {b.name: b.building_name for b in frappe.get_all(
        "Building", fields=["name", "building_name"], limit=500)}

    out = []
    for r in rows:
        head = r.expense_head or ""
        label = head.rsplit(" - ", 1)[0] if " - " in head else head
        out.append({
            "id": r.name,
            "date": str(r.expense_date),
            "head": label,
            "account": head,
            "group": group_of(head) or "",
            "amount": flt(r.amount),
            "basis": r.basis or "",
            "b": r.building or "",
            "bn": names.get(r.building, r.building or "\u2014"),
            "mode": r.payment_mode or "",
            "party": r.supplier or r.paid_from or "",
            "ref": r.reference or "",
            "what": r.description or "",
            "je": r.journal_entry or "",
        })

    total = sum(r["amount"] for r in out)
    direct = sum(r["amount"] for r in out if r["basis"] == BUILDING)
    common = sum(r["amount"] for r in out if r["basis"] == COMMON)
    unpaid = sum(r["amount"] for r in out if r["mode"] == "Unpaid")

    by_group = {}
    for r in out:
        by_group[r["group"] or "Ungrouped"] = round(
            by_group.get(r["group"] or "Ungrouped", 0.0) + r["amount"], 2)

    return {"rows": out, "frm": frm, "to": to,
            "total": round(total, 2),
            "direct": round(direct, 2),
            "common": round(common, 2),
            "unpaid": round(unpaid, 2),
            "count": len(out),
            "capped": len(out) >= int(limit or REGISTER_CAP),
            "by_group": by_group}


@frappe.whitelist()
def allocation_preview(frm=None, to=None):
    """How the common pool divides, and on what.

    Kept beside the register because the question "why is my building carrying
    9,400 of salary" is asked from the expense screen, not from a report.
    """
    guard(MD, GM, ACC)
    return allocation.preview(frm, to)


# ------------------------------------------------------------------- the chart

@frappe.whitelist()
def build_chart():
    """Create any missing group or head. Idempotent; safe to press twice."""
    guard(MD, ACC)
    out = ensure_chart()
    frappe.db.commit()
    return out
