"""Operations writes: collection cases, maintenance and move-out."""

import frappe
from frappe import _
from frappe.utils import flt, cint, today
from darkbrown.guards import guard, ACC, GM, MD, MNT
from darkbrown.permissions import require_building_access, require_record_access

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
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Collection Case", case)
    require_record_access(doc, "write")
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
        doc.promised_amount = flt(promised_amount)
        doc.broken_promise = 0
    elif outcome in ("No Answer", "Disputed") and doc.status == "Open":
        doc.status = "Contacted"
    doc.save()
    return {"case": doc.name, "status": doc.status,
            "security_deposit": doc.security_deposit}


@frappe.whitelist()
def escalate(case, reason=None):
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Collection Case", case)
    require_record_access(doc, "write")
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
    guard(MD, GM, ACC)
    require_record_access(frappe.get_doc("Tenancy Agreement", tenancy_agreement),
                          "read")
    from darkbrown.utils.collections_case import open_manual
    return open_manual(tenancy_agreement, reason)


# ---------------------------------------------------------------- maintenance

@frappe.whitelist()
def raise_job(payload):
    guard(MD, GM, MNT)
    data = frappe.parse_json(payload)
    if not data.get("building"):
        frappe.throw(_("A job needs a building."))
    require_building_access(data.get("building"))
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
        "recharge_amount": flt(data.get("recharge_amount")),
    }).insert()
    return {"case": doc.name, "status": doc.status,
            "security_deposit": doc.security_deposit}


@frappe.whitelist()
def advance_job(job, status, cost=None, notes=None, assigned_to=None):
    guard(MD, GM, MNT)
    doc = frappe.get_doc("Maintenance Request", job)
    require_record_access(doc, "write")
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
                                  "amount": flt(cost)})
    doc.save()
    return {"job": doc.name, "status": doc.status,
            "over_ceiling": bool(doc.over_ceiling)}


# ------------------------------------------------------------------ move-out

MO_STATUS = ["Notice Received", "Inspection Pending", "Inspection Done",
             "Settlement Pending", "Refund Pending", "Closed"]


@frappe.whitelist()
def open_moveout(payload):
    guard(MD, GM, ACC)
    data = frappe.parse_json(payload)
    ta = data.get("tenancy_agreement")
    if not ta:
        frappe.throw(_("A move-out hangs off a tenancy."))
    require_record_access(frappe.get_doc("Tenancy Agreement", ta), "read")
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

    # Both ends of the link. The approvals queue reads the deposit's side, so
    # writing only the case's side means a deposit release never reaches
    # anyone to approve.
    if doc.security_deposit:
        frappe.db.set_value("Security Deposit", doc.security_deposit,
                            "move_out_case", doc.name)
    return {"case": doc.name, "status": doc.status,
            "security_deposit": doc.security_deposit}


@frappe.whitelist()
def advance_moveout(case, payload):
    """Walks the case one step. Each step writes only its own fields, so a
    half-finished move-out never looks settled."""
    guard(MD, GM, ACC)
    data = frappe.parse_json(payload)
    doc = frappe.get_doc("Move Out Case", case)
    require_record_access(doc, "write")
    step = data.get("step")

    if step == "inspection":
        doc.status = "Inspection Done"
        doc.inspection_on = data.get("inspection_on") or today()
        doc.inspected_by = frappe.session.user
        doc.inspection_notes = data.get("notes")
        damages = flt(data.get("damages"))
        doc.damages_amount = damages
        # The custom workflow records inspection deductions as agreed values,
        # so expose them immediately in the case summary and carry them into
        # settlement.  Utilities remain separate to avoid counting them twice.
        doc.damages_charged = damages
        doc.utilities_due = flt(data.get("utilities_due"))
    elif step == "meters":
        doc.meter_readings = []
        for r in data.get("readings") or []:
            doc.append("meter_readings", {
                "meter_type": r.get("meter_type") or "Kahramaa",
                "meter_no": r.get("meter_no"),
                "reading": flt(r.get("reading")),
                "reading_date": r.get("reading_date") or today(),
                "amount_due": flt(r.get("amount_due")),
            })
        doc.utilities_due = sum(flt(r.amount_due) for r in doc.meter_readings)
        doc.status = "Settlement Pending"
    elif step == "keys":
        doc.keys_returned = 1
        doc.keys_returned_on = data.get("on") or today()
        doc.access_cards_returned = cint(data.get("cards"))
    elif step == "settle":
        doc.outstanding_rent = flt(data.get("outstanding_rent"))
        doc.damages_charged = flt(data.get("damages_charged"))
        doc.settlement_approved_by = frappe.session.user
        doc.status = "Refund Pending"
    elif step == "refund":
        doc.refund_method = data.get("method")
        doc.refund_paid_on = data.get("on") or today()
        doc.status = "Closed"
    else:
        frappe.throw(_("Unknown move-out step: {0}").format(step))

    doc.save()
    if step == "settle" and doc.security_deposit:
        total = (flt(doc.outstanding_rent) + flt(doc.utilities_due)
                 + flt(doc.damages_charged))
        held = flt(frappe.db.get_value(
            "Security Deposit", doc.security_deposit, "amount"))
        deductions = min(total, held)
        reasons = []
        for label, amount in (("Outstanding rent", doc.outstanding_rent),
                              ("Utilities", doc.utilities_due),
                              ("Damages", doc.damages_charged)):
            if flt(amount):
                reasons.append("{0}: QAR {1:,.2f}".format(label, flt(amount)))
        frappe.db.set_value("Security Deposit", doc.security_deposit, {
            "deductions": deductions,
            "deduction_reason": "; ".join(reasons),
            # Repair older cases that pre-date the reverse-link write in
            # open_moveout.  The approval queue intentionally reads from the
            # deposit side, so settlement must make that relationship whole.
            "move_out_case": doc.name,
        })
    return {"case": doc.name, "status": doc.status,
            "refund": flt(doc.refund_amount)}
