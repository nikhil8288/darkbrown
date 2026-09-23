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

JOB_TRANSITIONS = {
    "Open": {"Assigned", "Scheduled", "Cancelled"},
    "Assigned": {"Scheduled", "In Progress", "Cancelled"},
    "Scheduled": {"In Progress", "Cancelled"},
    "In Progress": {"Resolved", "Cancelled"},
    "Resolved": set(),
    "Cancelled": set(),
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
    building = data.get("building")
    require_building_access(building)
    unit = data.get("unit")
    if unit:
        unit_building = frappe.db.get_value("Unit", unit, "building")
        if not unit_building:
            frappe.throw(_("Unit {0} does not exist.").format(unit))
        if unit_building != building:
            frappe.throw(_("Unit {0} does not belong to {1}.").format(
                unit, building))

    estimated = flt(data.get("estimated_cost") or data.get("cost"))
    if estimated <= 0:
        frappe.throw(_("A maintenance job needs a positive estimated cost."))

    rechargeable = cint(data.get("rechargeable"))
    recharge_to = None
    recharge_tenancy = None
    if rechargeable:
        if not unit:
            frappe.throw(_("A tenant recharge needs the affected unit."))
        tenancies = frappe.get_all(
            "Tenancy Agreement",
            filters={"unit": unit, "building": building,
                     "status": ["in", ("Active", "Expiring")]},
            fields=["name", "tenant"], limit=2)
        if len(tenancies) != 1:
            frappe.throw(_(
                "{0} needs exactly one live tenancy before maintenance can "
                "be recharged.").format(unit))
        recharge_tenancy = tenancies[0].name
        recharge_to = tenancies[0].tenant
        supplied_customer = data.get("recharge_to")
        if supplied_customer and supplied_customer != recharge_to:
            frappe.throw(_("The recharge customer must match the live tenancy."))

    doc = frappe.get_doc({
        "doctype": "Maintenance Request",
        "building": building,
        "unit": unit,
        "category": data.get("category") or "Other",
        "priority": data.get("priority") or "Medium",
        "issue": data.get("issue"),
        "description": data.get("description"),
        "status": "Assigned" if data.get("assigned_to") else "Open",
        "assigned_to": data.get("assigned_to"),
        "rechargeable": rechargeable,
        "recharge_to": recharge_to,
        "recharge_tenancy": recharge_tenancy,
        "recharge_amount": (flt(data.get("recharge_amount"))
                            if rechargeable else 0),
        "cost_lines": [{"item": "Estimated job cost", "amount": estimated}],
    })
    if rechargeable and not doc.recharge_amount:
        doc.recharge_amount = estimated
    doc.insert()
    return {"case": doc.name, "status": doc.status,
            "cost": flt(doc.cost), "over_ceiling": bool(doc.over_ceiling),
            "recharge_to": doc.recharge_to}


@frappe.whitelist()
def advance_job(job, status, cost=None, notes=None, assigned_to=None,
                scheduled_on=None, recharge_amount=None):
    guard(MD, GM, MNT)
    doc = frappe.get_doc("Maintenance Request", job)
    require_record_access(doc, "write")
    allowed = JOB_TRANSITIONS.get(doc.status)
    if allowed is None or status not in allowed:
        frappe.throw(_("{0} cannot move from {1} to {2}.").format(
            job, doc.status, status))

    old_cost = flt(doc.cost)
    new_cost = flt(cost) if cost is not None else old_cost
    if new_cost < 0:
        frappe.throw(_("Maintenance cost cannot be negative."))
    cost_changed = cost is not None and abs(new_cost - old_cost) >= 0.005
    if doc.recharge_status == "Invoiced" and (
            cost_changed or recharge_amount is not None):
        frappe.throw(_(
            "An invoiced maintenance recharge cannot be changed. Cancel its "
            "Sales Invoice through the controlled correction workflow first."))
    if cost_changed:
        doc.ceiling_approved_by = None
        doc.ceiling_approved_on = None
        doc.cost_lines = []
        doc.append("cost_lines", {"item": "Actual job cost",
                                  "amount": new_cost})

    # Test the proposed cost, not the flag saved with the previous cost.  An
    # approved QAR 1,900 job edited to QAR 3,000 used to pass this gate first,
    # enter In Progress, then have validate() revoke its approval and mark it
    # over ceiling.  Work could therefore start in the same request that made
    # approval necessary.  Recompute after clearing any stale approval and
    # refuse the transition before status changes or anything is saved.
    ceiling = flt(frappe.db.get_single_value(
        "DBR Settings", "emergency_maintenance_ceiling"))
    needs_approval = bool(
        ceiling and doc.priority == "Emergency" and new_cost > ceiling
        and not doc.ceiling_approved_by)
    if needs_approval and status in ("In Progress", "Resolved"):
        frappe.throw(_(
            "{0} is above the emergency ceiling and needs MD approval "
            "before work starts.").format(job))

    effective_schedule = scheduled_on or doc.scheduled_on
    if status == "Scheduled" and not effective_schedule:
        frappe.throw(_("A scheduled maintenance job needs its scheduled date."))
    if status == "Resolved" and not (notes or doc.resolution_notes):
        frappe.throw(_("A resolved maintenance job needs resolution notes."))

    doc.status = status
    if assigned_to:
        doc.assigned_to = assigned_to
    if scheduled_on:
        doc.scheduled_on = scheduled_on
    if notes:
        doc.resolution_notes = notes
    if status == "Resolved":
        doc.resolved_on = frappe.utils.now()
    if recharge_amount is not None:
        if not doc.rechargeable:
            frappe.throw(_("That job is not marked for tenant recharge."))
        if doc.recharge_status == "Invoiced":
            frappe.throw(_("An invoiced maintenance recharge cannot be changed."))
        doc.recharge_amount = flt(recharge_amount)
    elif doc.rechargeable and cost is not None:
        doc.recharge_amount = new_cost
    if status == "Resolved" and doc.rechargeable and \
            flt(doc.recharge_amount) <= 0:
        frappe.throw(_("A rechargeable resolved job needs a positive amount."))
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
