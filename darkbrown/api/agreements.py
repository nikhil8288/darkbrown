"""Tenancy agreements and amendments.

Activation is self-approving. An agreement that has a QID on file and a signed
pack attached is complete, and a complete agreement does not need a second
person to say so — it activates on the spot and records that it took the self
approved route. Anything missing routes it for approval instead, and the
missing items are written down so the approver sees why it arrived.

Amendments are the opposite: a change to a live agreement always goes to a
human. Which human depends on the value at stake.
"""

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, add_days, date_diff

K = 1000.0


def _settings():
    return frappe.get_single("DBR Settings")


# ------------------------------------------------------------------ tenancy

@frappe.whitelist()
def create_agreement(payload):
    """Create a tenancy and settle its own activation in one pass.

    The unit is claimed here too. A unit already carrying a live tenancy is
    refused rather than quietly double-let.
    """
    data = frappe.parse_json(payload)

    unit = data.get("unit")
    if not unit:
        frappe.throw(_("A tenancy needs a unit."))
    if not frappe.db.exists("Unit", unit):
        frappe.throw(_("Unit {0} does not exist.").format(unit))

    live = frappe.get_all(
        "Tenancy Agreement",
        filters={"unit": unit, "status": ["in", ("Active", "Expiring",
                                                 "Pending Approval")]},
        pluck="name")
    if live:
        frappe.throw(_("Unit {0} already carries tenancy {1}.").format(
            unit, live[0]))

    tenant = _tenant(data.get("tenant") or {})
    building = frappe.db.get_value("Unit", unit, "building")
    settings = _settings()

    start = getdate(data.get("start_date") or today())
    end = data.get("end_date") or add_days(start, 364)

    doc = frappe.new_doc("Tenancy Agreement")
    doc.update({
        "tenant": tenant,
        "unit": unit,
        "building": building,
        "company": settings.default_company,
        "start_date": start,
        "end_date": end,
        "notice_days": (data.get("notice_days")
                        or settings.default_tenancy_notice_days or 60),
        "monthly_rent": flt(data.get("rent")) * K,
        "security_deposit": flt(data.get("deposit")) * K,
        "payment_mode": data.get("payment_mode") or "Cheque",
        "cheques_held": int(data.get("cheques_held") or 0),
        "qid_number": data.get("qid"),
        "qid_expiry": data.get("qid_expiry"),
        "passport_no": data.get("passport_no"),
        "mobile_no": data.get("mobile"),
        "signed_pack": data.get("signed_pack"),
        "notes": data.get("notes"),
        "auto_renew": int(data.get("auto_renew") or 0),
        "renewal_of": data.get("renewal_of"),
    })
    for c in data.get("charges") or []:
        doc.append("charges", {
            "charge_type": c.get("type") or "Other",
            "amount": flt(c.get("amount")) * K,
            "frequency": c.get("frequency") or "Monthly",
            "remarks": c.get("remarks"),
        })

    missing = _missing(doc)
    if missing:
        doc.status = "Pending Approval"
        doc.activation_route = "Routed for Approval"
        doc.missing_items = ", ".join(missing)
    else:
        doc.status = "Active"
        doc.activation_route = "Self Approved"
        doc.approved_by = frappe.session.user
        doc.approved_on = frappe.utils.now()

    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)

    if doc.status == "Active":
        _claim_unit(unit)
        _open_deposit(doc, data)

    return {"agreement": doc.name, "status": doc.status,
            "route": doc.activation_route,
            "missing": missing}


def _missing(doc):
    """What stops this agreement from standing on its own."""
    out = []
    if not doc.qid_number:
        out.append("QID not captured")
    if not doc.signed_pack:
        out.append("signed agreement not attached")
    if not flt(doc.monthly_rent):
        out.append("rent not set")
    if doc.payment_mode == "Cheque" and not int(doc.cheques_held or 0):
        out.append("no cheques logged")
    return out


@frappe.whitelist()
def activate(agreement, note=None):
    """Approve an agreement that was routed. The approver is standing in for
    the missing paperwork, so the reason is kept."""
    doc = frappe.get_doc("Tenancy Agreement", agreement)
    if doc.status != "Pending Approval":
        frappe.throw(_("Only an agreement pending approval can be activated. "
                       "{0} is {1}.").format(agreement, doc.status))
    doc.status = "Active"
    doc.approved_by = frappe.session.user
    doc.approved_on = frappe.utils.now()
    if note:
        doc.notes = (doc.notes or "") + f"\n\nActivated on override: {note}"
    doc.save(ignore_permissions=True)
    _claim_unit(doc.unit)
    return {"agreement": doc.name, "status": doc.status}


@frappe.whitelist()
def terminate(agreement, reason):
    doc = frappe.get_doc("Tenancy Agreement", agreement)
    doc.status = "Terminated"
    doc.notes = (doc.notes or "") + f"\n\nTerminated: {reason}"
    doc.save(ignore_permissions=True)
    if doc.unit and frappe.db.get_value("Unit", doc.unit, "status") == "Occupied":
        frappe.db.set_value("Unit", doc.unit, "status", "Vacant")
    return {"agreement": doc.name, "status": doc.status}


def _claim_unit(unit):
    if unit and frappe.db.get_value("Unit", unit, "status") != "Occupied":
        frappe.db.set_value("Unit", unit, "status", "Occupied")


def _tenant(t):
    """A tenant is an ERPNext Customer carrying the tenant flag."""
    if isinstance(t, str):
        return t
    existing = t.get("id")
    if existing:
        if not frappe.db.get_value("Customer", existing, "db_is_tenant"):
            frappe.db.set_value("Customer", existing, "db_is_tenant", 1)
        return existing

    name = (t.get("name") or "").strip()
    if not name:
        frappe.throw(_("A tenancy needs a tenant."))
    if frappe.db.exists("Customer", name):
        frappe.db.set_value("Customer", name, "db_is_tenant", 1)
        return name

    corp = bool(t.get("corporate"))
    group = (frappe.db.get_value("Customer Group",
                                 {"customer_group_name": "Commercial"}, "name")
             or frappe.db.get_value("Customer Group", {"is_group": 0}, "name"))
    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": name,
        "customer_type": "Company" if corp else "Individual",
        "customer_group": group,
        "db_is_tenant": 1,
        "db_tenant_category": "Company" if corp else "Individual",
        "db_qid": t.get("qid"),
        "db_qid_expiry": t.get("qid_expiry"),
        "db_cr_no": t.get("cr_no"),
        "db_passport_no": t.get("passport_no"),
        "db_mobile": t.get("mobile"),
    })
    doc.flags.ignore_mandatory = True
    return doc.insert(ignore_permissions=True).name


def _open_deposit(agreement, data):
    """A deposit that was taken is a liability from the moment it is taken."""
    amount = flt(agreement.security_deposit)
    if not amount:
        return
    doc = frappe.get_doc({
        "doctype": "Security Deposit",
        "tenancy_agreement": agreement.name,
        "tenant": agreement.tenant,
        "unit": agreement.unit,
        "company": agreement.company,
        "status": "Held",
        "amount": amount,
        "received_on": data.get("deposit_received_on") or today(),
        "receipt_method": data.get("deposit_method") or "Cheque",
    })
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------- amendments

@frappe.whitelist()
def request_amendment(payload):
    """Anything that changes a live agreement goes through here. The routing
    is decided by value, not by who is asking."""
    data = frappe.parse_json(payload)
    agreement = data.get("agreement")
    if not agreement:
        frappe.throw(_("An amendment needs an agreement."))

    reason = (data.get("reason") or "").strip()
    if not reason:
        frappe.throw(_("An amendment needs a reason."))

    ty = data.get("agreement_type") or "Tenancy Agreement"
    impact = flt(data.get("value_impact")) * K
    threshold = flt(_settings().amendment_md_threshold or 0)
    status = "Pending MD" if threshold and abs(impact) >= threshold else "Pending GM"

    doc = frappe.get_doc({
        "doctype": "Agreement Amendment",
        "agreement_type": ty,
        "agreement": agreement,
        "status": status,
        "effective_from": data.get("effective_from") or today(),
        "field_changed": data.get("field"),
        "old_value": str(data.get("old_value") or ""),
        "new_value": str(data.get("new_value") or ""),
        "value_impact": impact,
        "reason": reason,
        "requested_by": frappe.session.user,
        "requested_on": frappe.utils.now(),
    })
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return {"amendment": doc.name, "status": doc.status,
            "routed_to": "MD" if status == "Pending MD" else "GM"}


@frappe.whitelist()
def decide_amendment(amendment, decision, note=None):
    """Approve or reject. Approval applies the change; rejection never does."""
    doc = frappe.get_doc("Agreement Amendment", amendment)
    if doc.status not in ("Pending GM", "Pending MD"):
        frappe.throw(_("{0} is already {1}.").format(amendment, doc.status))

    roles = set(frappe.get_roles())
    if doc.status == "Pending MD" and not ({"Managing Director",
                                            "System Manager"} & roles):
        frappe.throw(_("This amendment is reserved for the Managing "
                       "Director."), frappe.PermissionError)

    if decision == "approve":
        doc.status = "Approved"
        doc.approved_by = frappe.session.user
        doc.approved_on = frappe.utils.now()
        _apply_amendment(doc)
    else:
        if not note:
            frappe.throw(_("A rejection needs a reason."))
        doc.status = "Rejected"
        doc.rejection_reason = note
    doc.save(ignore_permissions=True)
    return {"amendment": doc.name, "status": doc.status}


def _apply_amendment(doc):
    """Write the approved change onto the agreement it belongs to."""
    field = (doc.field_changed or "").strip()
    if not field or not doc.agreement:
        return
    meta = frappe.get_meta(doc.agreement_type)
    if not meta.get_field(field):
        return
    value = doc.new_value
    if meta.get_field(field).fieldtype == "Currency":
        value = flt(value)
    frappe.db.set_value(doc.agreement_type, doc.agreement, field, value)


# ------------------------------------------------------------------- renewal

@frappe.whitelist()
def renew(agreement, payload):
    """A renewal is a new agreement pointing at the one it replaces, not an
    edit. The history stays intact and the spread stays comparable."""
    data = frappe.parse_json(payload)
    old = frappe.get_doc("Tenancy Agreement", agreement)

    data.setdefault("unit", old.unit)
    data.setdefault("tenant", old.tenant)
    data.setdefault("rent", flt(data.get("rent") or old.monthly_rent / K))
    data.setdefault("deposit", flt(old.security_deposit) / K)
    data.setdefault("start_date", add_days(old.end_date, 1))
    data["renewal_of"] = old.name
    data.setdefault("qid", old.qid_number)
    data.setdefault("signed_pack", data.get("signed_pack"))

    old.status = "Expired"
    old.save(ignore_permissions=True)

    return create_agreement(frappe.as_json(data))


# ------------------------------------------------------------------- nightly

def nightly():
    """Move agreements into Expiring as they approach their end date, and out
    of Expiring once they pass it. Status is derived, never hand-set."""
    settings = _settings()
    window = int(settings.default_tenancy_notice_days or 60)
    for ta in frappe.get_all(
            "Tenancy Agreement",
            filters={"status": ["in", ("Active", "Expiring")]},
            fields=["name", "status", "end_date"]):
        if not ta.end_date:
            continue
        left = date_diff(ta.end_date, today())
        want = "Expired" if left < 0 else "Expiring" if left <= window else "Active"
        if want != ta.status:
            frappe.db.set_value("Tenancy Agreement", ta.name, "status", want)
    frappe.db.commit()
