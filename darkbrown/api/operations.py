"""Operations writes: collection cases, maintenance and move-out."""

import frappe
from frappe import _
from frappe.utils import flt, cint, today

K = 1000.0

STAGE_STATUS = {
    "Reminder sent": "Contacted",
    "Promise to pay": "Promised",
    "Promise broken": "Broken Promise",
    "Escalated": "Escalated",
    "Legal notice": "Legal",
}


@frappe.whitelist()
def log_contact(case, method, outcome, notes=None, promised_amount=None,
                promised_date=None):
    """Every touch on a case is a row in the log, not an overwrite of the last
    one. The stage follows from the outcome."""
    doc = frappe.get_doc("Collection Case", case)
    doc.append("actions", {
        "action_on": frappe.utils.now(),
        "method": method,
        "outcome": outcome,
        "notes": notes,
        "by_user": frappe.session.user,
    })
    if outcome == "Promised":
        if not promised_date:
            frappe.throw(_("A promise needs a date."))
        doc.status = "Promised"
        doc.promised_date = promised_date
        doc.promised_amount = flt(promised_amount) * K
        doc.broken_promise = 0
    elif outcome in ("No Answer", "Disputed") and doc.status == "Open":
        doc.status = "Contacted"
    doc.save()
    return doc.name


@frappe.whitelist()
def escalate(case, reason=None):
    doc = frappe.get_doc("Collection Case", case)
    if doc.status in ("Resolved", "Closed"):
        frappe.throw(_("That case is already closed."))
    doc.status = "Legal" if doc.status == "Escalated" else "Escalated"
    doc.escalated_on = today()
    doc.escalated_by = frappe.session.user
    doc.append("actions", {
        "action_on": frappe.utils.now(),
        "method": "Letter",
        "outcome": "Notice Served",
        "notes": reason or f"Escalated to {doc.status}.",
        "by_user": frappe.session.user,
    })
    doc.save()
    return doc.status


@frappe.whitelist()
def open_case(tenancy_agreement, reason):
    from darkbrown.utils.collections_case import open_manual
    return open_manual(tenancy_agreement, reason)


# ---------------------------------------------------------------- maintenance

@frappe.whitelist()
def raise_job(payload):
    data = frappe.parse_json(payload)
    if not data.get("building"):
        frappe.throw(_("A job needs a building."))
    doc = frappe.get_doc({
        "doctype": "Maintenance Request",
        "building": data.get("building"),
        "unit": data.get("unit"),
        "category": data.get("category") or "Other",
        "priority": data.get("priority") or "Medium",
        "issue": data.get("issue"),
        "description": data.get("description"),
        "status": "Open",
        "rechargeable": cint(data.get("rechargeable")),
        "recharge_to": data.get("recharge_to"),
        "recharge_amount": flt(data.get("recharge_amount")) * K,
    }).insert()
    return doc.name


@frappe.whitelist()
def advance_job(job, status, cost=None, notes=None, assigned_to=None):
    doc = frappe.get_doc("Maintenance Request", job)
    doc.status = status
    if assigned_to:
        doc.assigned_to = assigned_to
    if notes:
        doc.resolution_notes = notes
    if status == "Resolved":
        doc.resolved_on = frappe.utils.now()
    if cost is not None:
        doc.cost_lines = []
        doc.append("cost_lines", {"item": "Job cost",
                                  "amount": flt(cost) * K})
    doc.save()
    return {"job": doc.name, "status": doc.status,
            "over_ceiling": bool(doc.over_ceiling)}


# ------------------------------------------------------------------ move-out

MO_STATUS = ["Notice Received", "Inspection Pending", "Inspection Done",
             "Settlement Pending", "Refund Pending", "Closed"]


@frappe.whitelist()
def open_moveout(payload):
    data = frappe.parse_json(payload)
    ta = data.get("tenancy_agreement")
    if not ta:
        frappe.throw(_("A move-out hangs off a tenancy."))
    if frappe.db.exists("Move Out Case",
                        {"tenancy_agreement": ta,
                         "status": ["not in", ("Closed", "Cancelled")]}):
        frappe.throw(_("That tenancy already has a move-out running."))
    notice = frappe.db.get_value("Tenancy Agreement", ta, "notice_days") or 60
    doc = frappe.get_doc({
        "doctype": "Move Out Case",
        "tenancy_agreement": ta,
        "reason": data.get("reason") or "Tenant Notice",
        "status": "Notice Received",
        "notice_received_on": data.get("notice_received_on") or today(),
        "notice_days": notice,
        "planned_move_out": data.get("planned_move_out"),
        "security_deposit": frappe.db.get_value(
            "Security Deposit", {"tenancy_agreement": ta}, "name"),
    }).insert()
    return doc.name


@frappe.whitelist()
def advance_moveout(case, payload):
    """Walks the case one step. Each step writes only its own fields, so a
    half-finished move-out never looks settled."""
    data = frappe.parse_json(payload)
    doc = frappe.get_doc("Move Out Case", case)
    step = data.get("step")

    if step == "inspection":
        doc.status = "Inspection Done"
        doc.inspection_on = data.get("inspection_on") or today()
        doc.inspected_by = frappe.session.user
        doc.inspection_notes = data.get("notes")
        doc.damages_amount = flt(data.get("damages")) * K
    elif step == "meters":
        doc.meter_readings = []
        for r in data.get("readings") or []:
            doc.append("meter_readings", {
                "meter_type": r.get("meter_type") or "Kahramaa",
                "meter_no": r.get("meter_no"),
                "reading": flt(r.get("reading")),
                "reading_date": r.get("reading_date") or today(),
                "amount_due": flt(r.get("amount_due")) * K,
            })
        doc.utilities_due = sum(flt(r.amount_due) for r in doc.meter_readings)
        doc.status = "Settlement Pending"
    elif step == "keys":
        doc.keys_returned = 1
        doc.keys_returned_on = data.get("on") or today()
        doc.access_cards_returned = cint(data.get("cards"))
    elif step == "settle":
        doc.outstanding_rent = flt(data.get("outstanding_rent")) * K
        doc.damages_charged = flt(data.get("damages_charged")) * K
        doc.settlement_approved_by = frappe.session.user
        doc.status = "Refund Pending"
    elif step == "refund":
        doc.refund_method = data.get("method")
        doc.refund_paid_on = data.get("on") or today()
        doc.status = "Closed"
    else:
        frappe.throw(_("Unknown move-out step: {0}").format(step))

    doc.save()
    return {"case": doc.name, "status": doc.status,
            "refund": flt(doc.refund_amount) / K}
