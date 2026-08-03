"""People: staff on DarkBrown's own payroll, and what they cost.

This module exists for the money before it exists for the people. Salaries are
a large, fixed, monthly operating cost and until now they were recorded
nowhere, which meant three things were quietly wrong: the spread bridge ended
at a figure that had never met payroll, the thirteen-week runway showed no
outflow for the single most reliable payment this business makes, and any
reserve floor computed from that cost base was short by the same amount every
month.

Two rules hold it together.

    Staff cost is portfolio overhead and does not reach building margin (D74).
    Nobody here is charged to a building. Building margin stays what it has
    always been — the spread after head-lease — and overhead is subtracted
    once, at portfolio level, where it actually falls. Spreading it across
    buildings on some invented key would make every building's margin a matter
    of the allocation rule rather than the lease.

    Pay figures are for Accounts and the MD (D76). The General Manager gets
    headcount, names and departments and no money at all, which is what the
    role needs to plan cover. Masking happens here, on the server, and not in
    the shell — a figure withheld only by the front end is not withheld.
"""

import json

import frappe
from frappe.utils import flt, getdate, today


def _payload(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload or {}


def can_see_pay(user=None):
    """The MD and Accounts see money. Nobody else does, whatever they ask."""
    roles = set(frappe.get_roles(user or frappe.session.user))
    return bool(roles & {"Managing Director", "Accounts", "System Manager"})


# ---------------------------------------------------------------- the list

@frappe.whitelist()
def staff_list(include_left=0):
    """Everyone, with pay attached only for those entitled to see it.

    The rows are built field by field rather than by handing back the whole
    document, so a pay figure cannot arrive on a screen that was never meant
    to carry one.
    """
    filters = {} if int(include_left or 0) else {"status": "Active"}
    rows = frappe.get_all(
        "Staff Member", filters=filters,
        fields=["name", "full_name", "job_title", "department", "status",
                "joined_on", "left_on", "qid_number", "basic_salary",
                "allowances", "monthly_cost"],
        order_by="department asc, full_name asc", ignore_permissions=True)

    pay = can_see_pay()
    out = []
    for r in rows:
        row = {
            "id": r.name,
            "name": r.full_name,
            "title": r.job_title or "",
            "dept": r.department,
            "status": r.status,
            "joined": str(r.joined_on) if r.joined_on else "",
            "left": str(r.left_on) if r.left_on else "",
            "qid": r.qid_number or "",
        }
        if pay:
            row["basic"] = flt(r.basic_salary)
            row["allow"] = flt(r.allowances)
            row["cost"] = flt(r.monthly_cost)
        out.append(row)
    return {"rows": out, "pay": pay}


@frappe.whitelist()
def staff_member(name):
    """One record. Same masking as the list."""
    doc = frappe.get_doc("Staff Member", name)
    out = {
        "id": doc.name, "name": doc.full_name, "title": doc.job_title or "",
        "dept": doc.department, "status": doc.status,
        "joined": str(doc.joined_on) if doc.joined_on else "",
        "left": str(doc.left_on) if doc.left_on else "",
        "qid": doc.qid_number or "", "notes": doc.notes or "",
    }
    if can_see_pay():
        out.update({"basic": flt(doc.basic_salary),
                    "allow": flt(doc.allowances),
                    "cost": flt(doc.monthly_cost)})
    return out


# --------------------------------------------------------------- the write

@frappe.whitelist()
def save_staff(payload):
    """Create or update. Pay only moves if the caller is allowed to see it —
    otherwise an edit by the General Manager would silently write a blank
    salary over a real one."""
    p = _payload(payload)
    name = p.get("id")

    doc = (frappe.get_doc("Staff Member", name) if name
           else frappe.new_doc("Staff Member"))

    for field, key in (("full_name", "name"), ("job_title", "title"),
                       ("department", "dept"), ("status", "status"),
                       ("qid_number", "qid"), ("notes", "notes")):
        if key in p:
            setattr(doc, field, p.get(key))
    if p.get("joined"):
        doc.joined_on = getdate(p["joined"])
    if p.get("left"):
        doc.left_on = getdate(p["left"])

    if can_see_pay():
        if "basic" in p:
            doc.basic_salary = flt(p.get("basic"))
        if "allow" in p:
            doc.allowances = flt(p.get("allow"))
    elif not name:
        frappe.throw("A staff record cannot be created without pay details. "
                     "Ask Accounts or the Managing Director to add it.")

    doc.save(ignore_permissions=False)
    frappe.db.commit()
    return {"id": doc.name, "name": doc.full_name,
            "cost": flt(doc.monthly_cost) if can_see_pay() else None}


# ----------------------------------------------------------------- the cost

def monthly_staff_cost(on=None):
    """Total monthly staff cost as at a date — the figure the cost base wants.

    Deliberately not whitelisted. It is a number for the server to fold into
    the bridge and the runway, and it is reachable from the screens through
    staff_summary, which applies the pay rule. Exposing it directly would hand
    a total salary bill to anyone who could call it.

    Anyone who had left before the date is out; anyone who had not yet joined
    is out. Both matter for a back-dated month, and neither is guesswork.
    """
    on = getdate(on or today())
    rows = frappe.get_all(
        "Staff Member",
        fields=["monthly_cost", "joined_on", "left_on", "status"],
        ignore_permissions=True)
    total = 0.0
    for r in rows:
        if r.joined_on and getdate(r.joined_on) > on:
            continue
        if r.left_on and getdate(r.left_on) < on:
            continue
        if r.status == "Left" and not r.left_on:
            continue
        total += flt(r.monthly_cost)
    return total


@frappe.whitelist()
def staff_summary(on=None):
    """Headcount for everyone, cost for those entitled to it."""
    on = getdate(on or today())
    heads = frappe.db.sql("""
        select department, count(*) n
        from `tabStaff Member`
        where status = 'Active'
        group by department order by department
    """, as_dict=True)
    out = {
        "headcount": sum(int(h.n) for h in heads),
        "byDept": [{"dept": h.department, "n": int(h.n)} for h in heads],
        "pay": can_see_pay(),
    }
    if out["pay"]:
        out["monthly"] = monthly_staff_cost(on)
        out["annual"] = out["monthly"] * 12
    return out
