"""Money in, money out.

Two rules hold this module together.

ERPNext owns the ledger. Nothing here writes a GL entry by hand; it creates
Sales Invoices and Payment Entries and lets ERPNext post them. That keeps one
set of books rather than two that disagree.

A returned cheque is an event, not a status. Bouncing a cheque reverses the
payment, reopens what it settled, and leaves a record of why — because the
question asked later is always "what happened", not "what is it now".
"""

import calendar
import secrets

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, add_days, add_months, date_diff
from darkbrown.guards import guard, ACC, GM, MD
from darkbrown.permissions import (
    allowed_buildings,
    require_building_access,
    require_record_access,
    require_tenant_access,
)


_FREQUENCY_MONTHS = {
    "Monthly": 1,
    "Quarterly": 3,
    "Half Yearly": 6,
    "Annual": 12,
}

def _settings():
    return frappe.get_single("DBR Settings")


def _company():
    return (_settings().default_company
            or frappe.db.get_value("Company", {}, "name"))


def _outgoing_head_lease(data, party, cheque_date):
    """Resolve the contract that an outgoing landlord cheque belongs to.

    Supplier payment allocation is contract-scoped.  Letting a head-lease
    cheque reach clearing without this link makes it eligible for the
    supplier's unrelated open bills, which is worse than refusing ambiguous
    input.  A caller may name the lease; otherwise one unambiguous live lease
    for the landlord and cheque date is inferred.
    """
    purpose = data.get("purpose") or "Other"
    requested = data.get("head_lease")
    if purpose not in ("Head-lease rent", "Deposit to landlord") and not requested:
        return None

    if requested:
        if not frappe.db.exists("Head Lease", requested):
            frappe.throw(_("Head Lease {0} does not exist.").format(requested))
        lease = frappe.get_doc("Head Lease", requested)
        require_record_access(lease, "read")
        if lease.landlord != party:
            frappe.throw(_(
                "Head Lease {0} belongs to {1}, not {2}."
            ).format(requested, lease.landlord, party))
        return lease

    candidates = frappe.get_all(
        "Head Lease",
        filters={"landlord": party,
                 "status": ["in", ("Active", "Expiring")]},
        fields=["name", "building", "landlord", "start_date", "end_date"])
    on = getdate(cheque_date)
    candidates = [x for x in candidates
                  if (not x.start_date or getdate(x.start_date) <= on)
                  and (not x.end_date or getdate(x.end_date) >= on)]
    if not candidates:
        frappe.throw(_(
            "No active Head Lease for {0} covers the cheque date {1}."
        ).format(party, on))
    if len(candidates) > 1:
        frappe.throw(_(
            "{0} has multiple Head Leases covering {1}; choose the contract."
        ).format(party, on))
    return frappe.get_doc("Head Lease", candidates[0].name)


# -------------------------------------------------------------------- cheques

@frappe.whitelist()
def log_cheque(payload):
    """Log one cheque, or a book of post-dated cheques in one pass.

    A tenant paying by cheque hands over several at signing. Logging them one
    at a time is where mistakes get made, so a count and a first number is
    enough to lay the whole series down.
    """
    guard(MD, ACC)
    frappe.throw(_("The cheque register is deferred. Keep cheque records manually for now."))
    data = frappe.parse_json(payload)
    count = int(data.get("count") or 1)
    if count < 1:
        frappe.throw(_("A cheque batch needs at least one cheque."))

    first_no = str(data.get("cheque_no") or "").strip()
    if not first_no:
        frappe.throw(_("A cheque needs its number."))

    direction = data.get("direction") or "Incoming"
    if direction not in ("Incoming", "Outgoing"):
        frappe.throw(_("Cheque direction must be Incoming or Outgoing."))
    agreement = data.get("tenancy_agreement")
    ta = frappe.get_doc("Tenancy Agreement", agreement) if agreement else None
    amount = flt(data.get("amount"))
    if not amount and ta:
        amount = flt(ta.monthly_rent)
    if amount <= 0:
        frappe.throw(_("A cheque amount must be greater than zero."))
    party = data.get("party") or (ta.tenant if ta else None)
    if not party:
        frappe.throw(_("A cheque needs a party."))

    first_date = getdate(data.get("cheque_date") or today())
    lease = (_outgoing_head_lease(data, party, first_date)
             if direction == "Outgoing" else None)
    building = (ta.building if ta else lease.building if lease
                else data.get("building") or (
                    frappe.db.get_value("Unit", data.get("unit"), "building")
                    if data.get("unit") else None))
    if ta:
        require_record_access(ta, "read")
    elif lease:
        require_record_access(lease, "read")
    else:
        require_building_access(building)

    every = int(data.get("months_apart") or 1)
    numeric = first_no.isdigit()

    made = []
    for i in range(count):
        no = str(int(first_no) + i) if numeric else (
            first_no if count == 1 else f"{first_no}-{i + 1}")
        doc = frappe.get_doc({
            "doctype": "Cheque",
            "direction": direction,
            "party_type": "Customer" if direction == "Incoming" else "Supplier",
            "party": party,
            "status": "Received" if direction == "Incoming" else "Issued",
            "company": _company(),
            "cheque_no": no,
            "bank": data.get("bank"),
            "cheque_date": add_months(first_date, i * every),
            "amount": amount,
            "cheque_book": data.get("cheque_book"),
            "scan": data.get("scan"),
            "building": building,
            "unit": ta.unit if ta else data.get("unit"),
            "tenancy_agreement": agreement,
            "head_lease": lease.name if lease else data.get("head_lease"),
            "purpose": data.get("purpose") or (
                "Rent" if direction == "Incoming" else "Other"),
            "notes": data.get("notes"),
        })
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        made.append(doc.get("name"))

    if ta:
        ta.db_set("cheques_held", flt(ta.cheques_held) + count,
                  update_modified=False)

    return {"cheques": made, "count": len(made)}


@frappe.whitelist()
def record_incoming_cheque(payload):
    """Receive a tenant cheque without posting an invoice payment yet."""
    guard(MD, ACC)
    data = frappe.parse_json(payload)
    tenant = data.get("tenant")
    if not tenant:
        frappe.throw(_("Choose a tenant."))
    require_tenant_access(tenant)
    amount = flt(data.get("amount"), 2)
    number = str(data.get("cheque_no") or "").strip()
    bank = str(data.get("cheque_bank") or "").strip()
    if amount <= 0 or not number or not bank or not data.get("cheque_date"):
        frappe.throw(_("Enter the cheque number, drawn-on bank, date and positive amount."))
    invoice = data.get("invoice")
    unit = agreement = None
    if invoice:
        si = frappe.get_doc("Sales Invoice", invoice)
        if (si.docstatus != 1 or si.customer != tenant
                or flt(si.outstanding_amount) <= 0):
            frappe.throw(_("Choose an outstanding invoice for this tenant."))
        agreement = si.get("custom_rental_agreement") or None
        if agreement:
            ta = frappe.get_doc("Tenancy Agreement", agreement)
            if ta.tenant != tenant:
                frappe.throw(_("The invoice agreement does not belong to this tenant."))
            unit = ta.unit
    if not unit:
        agreements = frappe.get_all("Tenancy Agreement",
            filters={"tenant": tenant, "status": ["in", ["Active", "Expiring"]]},
            fields=["name", "unit"], limit_page_length=100)
        if len(agreements) != 1:
            frappe.throw(_("Choose a tenant invoice with one identifiable unit before receiving this cheque."))
        agreement, unit = agreements[0].name, agreements[0].unit
    building = frappe.db.get_value("Unit", unit, "building")
    require_building_access(building)
    frappe.db.sql("SELECT name FROM `tabCustomer` WHERE name = %s FOR UPDATE", (tenant,))
    if frappe.db.exists("Cheque", {"direction": "Incoming", "party": tenant,
                                   "cheque_no": number, "status": ["!=", "Cancelled"]}):
        frappe.throw(_("This cheque number is already recorded for the tenant."))
    doc = frappe.get_doc({"doctype": "Cheque", "direction": "Incoming",
        "party_type": "Customer", "party": tenant, "company": _company(),
        "status": "Received", "cheque_no": number, "bank": bank,
        "cheque_date": data.get("cheque_date"),
        "received_on": data.get("on") or today(), "amount": amount,
        "payment_entry": None,
        "building": building, "unit": unit, "tenancy_agreement": agreement,
        "sales_invoice": invoice, "head_lease": None, "purpose": "Rent",
        "notes": data.get("reference")})
    doc.insert(ignore_permissions=True)
    return {"cheque": doc.name, "amount": _kk(amount), "status": doc.status}


@frappe.whitelist()
def attach_payment_cheque_image(cheque, file_url):
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", cheque)
    require_record_access(doc, "write")
    if not str(file_url or "").lower().endswith((".jpg", ".jpeg", ".png")):
        frappe.throw(_("Choose a JPG or PNG cheque image."))
    if not frappe.db.get_value("File", {"file_url": file_url,
            "attached_to_doctype": "Cheque", "attached_to_name": cheque,
            "is_private": 1}, "name"):
        frappe.throw(_("Upload a private image attached to this cheque."))
    doc.scan = file_url
    doc.save(ignore_permissions=True)
    return {"cheque": cheque, "scan": file_url}


# -------------------------------------------------------------- cheque helpers

def is_security_cheque(cheque):
    """Is this cheque a tenant's security deposit rather than rent?

    There is no cheque_type field and there does not need to be: a security
    cheque is the one a Security Deposit record points at through
    receipt_cheque. One fact, one place. The safety property is that a security
    cheque must NEVER create income - it is a refundable liability - so
    clear_cheque refuses it and sends the caller to bank_security_deposit().
    """
    return bool(frappe.db.exists("Security Deposit",
                                 {"receipt_cheque": cheque}))


def _mark_headlease_payment(cheque, status):
    """An outgoing cheque against a head lease carries the payment row with it,
    so the schedule and the register cannot disagree."""
    if not cheque.head_lease:
        return
    row = frappe.db.get_value("Head Lease Payment",
                              {"cheque": cheque.name}, "name")
    if row:
        frappe.db.set_value("Head Lease Payment", row, "status", status)


def _book_return_charge(cheque):
    """A returned cheque costs us a bank charge. It is a real expense and it
    belongs in the P&L against the building, not stored on the cheque row and
    forgotten.

    Booked as a DRAFT Journal Entry - Dr charge account / Cr bank - matching
    the drafts-first policy used elsewhere. If no charge account is configured
    in DBR Settings the charge is skipped and reported, rather than guessed at.
    """
    charge = flt(cheque.return_charge)
    if charge <= 0:
        return None
    account = _settings().returned_cheque_charge_account
    if not account:
        return None
    company = _company()
    bank = _paid_to(cheque.bank_account or _settings().default_bank_account,
                    company)
    if not bank:
        return None

    je = frappe.new_doc("Journal Entry")
    je.company = company
    je.posting_date = cheque.returned_on or today()
    je.user_remark = (f"Bank charge on returned cheque {cheque.cheque_no} "
                      f"({cheque.party or ''}). Cheque {cheque.name}.")
    cc = _cost_center(cheque.building) if cheque.building else None
    je.append("accounts", {"account": account,
                           "debit_in_account_currency": charge,
                           "cost_center": cc})
    je.append("accounts", {"account": bank,
                           "credit_in_account_currency": charge,
                           "cost_center": cc})
    je.flags.ignore_permissions = True
    je.insert()
    return je.name


@frappe.whitelist()
def present_cheque(cheque, bank_account=None, on=None):
    """Send a cheque to the bank. It is out of our hands from here."""
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", cheque)
    require_record_access(doc, "write")
    allowed = (("Received", "Deposited") if doc.direction == "Incoming"
               else ("Issued",))
    if doc.status not in allowed:
        frappe.throw(_("{0} is {1} and cannot be presented.").format(
            cheque, doc.status))
    doc.status = "Presented"
    doc.presented_on = on or today()
    doc.bank_account = bank_account or _settings().default_bank_account
    doc.save(ignore_permissions=True)
    return {"cheque": doc.name, "status": doc.status}


@frappe.whitelist()
def clear_cheque(cheque, on=None):
    """The cheque cleared. That is a receipt, so the ledger gets one."""
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", cheque)
    require_record_access(doc, "write")
    if doc.status == "Cleared":
        return {"cheque": doc.name, "status": doc.status,
                "payment_entry": doc.payment_entry}
    allowed = (("Presented", "Deposited", "Received")
               if doc.direction == "Incoming" else ("Presented", "Issued"))
    if doc.status not in allowed:
        frappe.throw(_("{0} is {1} and cannot clear.").format(
            cheque, doc.status))
    if is_security_cheque(doc.name):
        frappe.throw(_(
            "{0} is a SECURITY cheque and must not create income. If it was "
            "actually banked, use bank_security_deposit - that books "
            "Dr Bank / Cr Security Deposits Held, a refundable liability."
        ).format(cheque))

    # New payment cheques cannot be declared cleared by a form or a direct
    # API call. A matching imported bank line is the evidence for clearing.
    if doc.get("received_on") or doc.get("purchase_invoice"):
        matched = frappe.db.get_value("Bank Statement Line", {
            "status": "Matched",
            "matched_type": "Deposit Batch" if doc.direction == "Incoming" else "Cheque",
            "matched_ref": doc.get("deposit_batch") if doc.direction == "Incoming" else doc.name,
        }, ["parent", "txn_date"], as_dict=True)
        if (not matched or frappe.db.get_value("Bank Statement Import",
                matched.parent, "bank_account") != doc.bank_account):
            frappe.throw(_("Clear this cheque through a matched bank statement."))
        on = str(matched.txn_date)

    doc.status = "Cleared"
    doc.cleared_on = on or today()
    if doc.party and not doc.payment_entry:
        if doc.direction == "Incoming":
            doc.payment_entry = _receipt(doc.party, flt(doc.amount),
                                         doc.cleared_on, doc.bank_account,
                                         reference=doc.name,
                                         invoice=doc.get("sales_invoice"))[0]
        else:
            doc.payment_entry = _supplier_payment(
                doc.party, flt(doc.amount), doc.cleared_on, doc.bank_account,
                reference=doc.name, head_lease=doc.head_lease,
                invoice=doc.get("purchase_invoice"))[0]
    doc.save(ignore_permissions=True)
    _mark_headlease_payment(doc, "Cleared")
    return {"cheque": doc.name, "status": doc.status,
            "payment_entry": doc.payment_entry}


@frappe.whitelist()
def return_cheque(cheque, reason, charge=None, notes=None, on=None):
    """A bounce. Reverse the money, then open a case if one is warranted —
    both, in one pass, because a bounce that only changes a status is a bounce
    nobody chases."""
    guard(MD, ACC)
    doc = frappe.get_doc("Cheque", cheque)
    require_record_access(doc, "write")
    if doc.status == "Returned":
        frappe.throw(_("{0} is already recorded as returned.").format(cheque))

    # Reverse the money first. Cancelling the Payment Entry runs a hook that
    # writes to this cheque's row, so a copy read before that point carries a
    # stale timestamp and the save is refused as a conflict. Reload, then
    # apply the bounce to the fresh copy.
    if doc.payment_entry:
        # Payment Entry cancellation deliberately clears ``cleared_on`` while
        # it restores the cheque's prior operational state.  A return is
        # different: Cleared remains a real, completed audit event even though
        # its accounting entry is reversed.  Preserve that event timestamp
        # across the cancellation hook so the lifecycle stays immutable.
        cleared_on = doc.cleared_on
        pe = frappe.get_doc("Payment Entry", doc.payment_entry)
        if pe.docstatus == 1:
            pe.cancel()
        doc.reload()
        doc.payment_entry = None
        doc.cleared_on = cleared_on

    doc.status = "Returned"
    doc.returned_on = on or today()
    doc.return_reason = reason
    doc.return_charge = flt(charge) if charge else 0
    doc.return_notes = notes
    doc.save(ignore_permissions=True)
    _mark_headlease_payment(doc, "Returned")

    # The bank charge is a real cost and gets booked. Previously it was stored
    # on the cheque row and never reached the P&L.
    charge_je = _book_return_charge(doc)

    case = None
    if doc.direction == "Incoming" and doc.tenancy_agreement:
        case = _case_for_bounce(doc)

    return {"cheque": doc.name, "status": doc.status, "case": case,
            "charge_journal_entry": charge_je,
            "charge_unbooked": bool(flt(doc.return_charge) > 0
                                    and not charge_je)}


def _case_for_bounce(cheque):
    """A bounce opens a collection case unless the tenancy already has one.

    The bounce is recorded as a comment rather than a contact action — an
    action row means somebody spoke to the tenant, and nobody has yet.
    """
    note = (f"Cheque {cheque.cheque_no} for QAR {flt(cheque.amount):,.0f} "
            f"returned: {cheque.return_reason}.")

    invoice_exposure = sum(flt(r.outstanding_amount) for r in frappe.get_all(
        "Sales Invoice",
        filters={"customer": cheque.party, "docstatus": 1,
                 "outstanding_amount": [">", 0]},
        fields=["outstanding_amount"]))
    exposure = max(invoice_exposure, flt(cheque.amount))

    from darkbrown.utils.collections_case import open_case
    name = open_case(
        cheque.tenancy_agreement, "Returned Cheque", reference=cheque.name,
        outstanding=exposure)
    if name:
        frappe.get_doc("Collection Case", name).add_comment("Comment", note)
    return name


@frappe.whitelist()
def replace_cheque(cheque, payload):
    """A replacement points back at what it replaces."""
    guard(MD, ACC)
    data = frappe.parse_json(payload)
    old = frappe.get_doc("Cheque", cheque)
    require_record_access(old, "write")
    data.setdefault("party", old.party)
    data.setdefault("tenancy_agreement", old.tenancy_agreement)
    data.setdefault("amount", flt(old.amount))
    data.setdefault("count", 1)
    made = log_cheque(frappe.as_json(data))
    new = made["cheques"][0]
    old.db_set("replaced_by", new, update_modified=False)
    old.db_set("status", "Replaced", update_modified=False)
    return {"replaced": old.name, "cheque": new}


# -------------------------------------------------------------- invoice runs

def _months_between(left, right):
    return (right.year - left.year) * 12 + right.month - left.month


def _month_end(value):
    value = getdate(value)
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def _add_months_first(value, months):
    value = getdate(value).replace(day=1)
    index = value.year * 12 + value.month - 1 + months
    return value.replace(year=index // 12, month=index % 12 + 1)


def _prorated_monthly(monthly_amount, start, end):
    """Calendar-day accrual for a monthly amount, inclusive at both ends."""
    start, end = getdate(start), getdate(end)
    if end < start:
        return 0
    total, cursor = 0.0, start
    while cursor <= end:
        last = min(_month_end(cursor), end)
        days = (last - cursor).days + 1
        total += flt(monthly_amount) * days / calendar.monthrange(
            cursor.year, cursor.month)[1]
        cursor = getdate(add_days(last, 1))
    return flt(total, 2)


def _billing_window(agreement, period_start):
    """Return the contract window billed by this monthly run, or ``None``.

    The payment frequency controls when a bill falls due, not the monthly
    economics. Quarterly, half-yearly and annual bills therefore collect the
    calendar-day accrual for their whole forward cycle in the cycle's first
    month. Partial first and final months follow the signed contract dates.
    """
    period_start = getdate(period_start).replace(day=1)
    contract_start, contract_end = (getdate(agreement.start_date),
                                    getdate(agreement.end_date))
    if contract_end < period_start:
        return None
    months = _FREQUENCY_MONTHS.get(agreement.payment_frequency)
    if not months:
        frappe.throw(_("Unsupported payment frequency on {0}: {1}").format(
            agreement.name, agreement.payment_frequency))
    first_cycle = contract_start.replace(day=1)
    offset = _months_between(first_cycle, period_start)
    if offset < 0 or offset % months:
        return None
    cycle_end = getdate(add_days(_add_months_first(period_start, months), -1))
    start = max(period_start, contract_start)
    end = min(cycle_end, contract_end)
    return (start, end) if start <= end else None


def _charge_amount(charge, agreement, period_start, window):
    frequency = charge.frequency or "Monthly"
    if frequency == "One Time":
        return flt(charge.amount, 2) if getdate(period_start).replace(
            day=1) == getdate(agreement.start_date).replace(day=1) else 0
    months = _FREQUENCY_MONTHS.get(frequency)
    if not months:
        frappe.throw(_("Unsupported recurring-charge frequency: {0}").format(
            frequency))
    offset = _months_between(getdate(agreement.start_date).replace(day=1),
                             getdate(period_start).replace(day=1))
    if offset < 0 or offset % months:
        return 0
    if frequency == "Monthly":
        return _prorated_monthly(charge.amount, window[0], window[1])
    return flt(charge.amount, 2)


def _maintenance_recharge_account(company):
    account = frappe.db.get_value(
        "Account", {"company": company,
                    "account_name": "Tenant Recharge Income",
                    "root_type": "Income", "is_group": 0}, "name")
    if not account:
        frappe.throw(_(
            "Configure Tenant Recharge Income before billing maintenance "
            "recharges."))
    return account


def _utility_recovery_account(company):
    account = frappe.db.get_value(
        "Account", {"company": company,
                    "account_name": "Utility Recovery",
                    "root_type": "Income", "is_group": 0}, "name")
    if not account:
        # A deploy can update Python without running after_migrate.  The
        # foundation normally creates this leaf there; recover idempotently at
        # the first draft rather than making every utility allocation unusable.
        # The helper creates an Account only — never a voucher or GL Entry.
        from darkbrown.utils.accounting_setup import \
            ensure_utility_recovery_account
        account = ensure_utility_recovery_account(company)
    if not account:
        frappe.throw(_(
            "Configure Utility Recovery before billing tenant utility shares."))
    return account


def _invoice_run_name(building, period_start):
    """A stable period name with suffixes for audited replacements."""
    base = "INV-{0}-{1}".format(building, period_start)
    name, suffix = base, 2
    while frappe.db.exists("Invoice Run", name):
        name = "{0}-{1}".format(base, suffix)
        suffix += 1
    return name


@frappe.whitelist()
def build_invoice_run(building, period_start=None):
    """Draft a month of rent for one building.

    Nothing is issued here. The run is a proposal the Accounts officer reads
    line by line, with the variance against each agreement shown, and only
    then does it go anywhere.
    """
    guard(MD, GM, ACC)
    require_building_access(building)
    start = getdate(period_start or today()).replace(day=1)
    end = add_days(add_months(start, 1), -1)

    if frappe.db.exists("Invoice Run", {"building": building,
                                        "period_start": start,
                                        "status": ["!=", "Cancelled"]}):
        frappe.throw(_("A run already exists for {0} in that period.").format(
            building))

    agreements = frappe.get_all(
        "Tenancy Agreement",
        filters={"building": building,
                 "status": ["in", ("Active", "Expiring")]},
        fields=["name", "tenant", "unit", "monthly_rent", "start_date",
                "end_date", "payment_frequency"])
    if not agreements:
        frappe.throw(_("{0} has no live tenancies to invoice.").format(building))

    run = frappe.get_doc({
        "doctype": "Invoice Run",
        "building": building,
        "period_start": start,
        "period_end": end,
        "status": "Draft",
        "company": _company(),
        "generated_by": frappe.session.user,
        "generated_on": frappe.utils.now(),
    })
    # The DocType's format name identifies the period, but a cancelled run is
    # deliberately retained.  Mark the suffix-aware name as explicit so
    # Frappe does not reapply the format rule and collide with the audit copy.
    run.name = _invoice_run_name(building, start)
    run.flags.name_set = True

    maintenance = frappe.get_all(
        "Maintenance Request",
        filters={"building": building, "status": "Resolved",
                 "rechargeable": 1, "recharge_status": "Pending",
                 "recharge_invoice_run": ["is", "not set"],
                 "recharge_amount": [">", 0]},
        fields=["name", "unit", "recharge_to", "recharge_tenancy",
                "recharge_amount", "issue"],
        order_by="resolved_on asc, creation asc")
    maintenance_account = (_maintenance_recharge_account(_company())
                           if maintenance else None)
    queued_recharges = set()

    utility_bills = frappe.get_all(
        "Utility Bill",
        filters={"building": building,
                 "status": ["in", ("Allocated", "Recovered")],
                 "period_end": ["<=", end]},
        fields=["name", "bill_no", "utility_type", "period_end"],
        order_by="period_end asc, creation asc")
    utility_by_name = {b.name: b for b in utility_bills}
    utility_allocations = (frappe.get_all(
        "Utility Bill Allocation",
        filters={"parent": ["in", list(utility_by_name)],
                 "sales_invoice": ["is", "not set"],
                 "invoice_run": ["is", "not set"]},
        fields=["name", "parent", "unit", "tenant", "amount"])
        if utility_by_name else [])
    utility_account = (_utility_recovery_account(_company())
                       if utility_allocations else None)
    queued_utility = set()

    total, variance_seen = 0, False
    for a in agreements:
        window = _billing_window(a, start)
        agreed = (_prorated_monthly(a.monthly_rent, *window)
                  if window else 0)
        snapshots = []
        if window:
            for charge in frappe.get_all(
                    "Tenancy Charge", filters={"parent": a.name},
                    fields=["charge_type", "amount", "frequency",
                            "income_account", "remarks"]):
                charge_amount = _charge_amount(charge, a, start, window)
                if charge_amount:
                    snapshots.append({"type": charge.charge_type,
                                      "amount": charge_amount,
                                      "income_account": charge.income_account,
                                      "remarks": charge.remarks})
        for job in maintenance:
            belongs = (job.recharge_tenancy == a.name or (
                not job.recharge_tenancy and job.recharge_to == a.tenant
                and job.unit == a.unit))
            if not belongs:
                continue
            snapshots.append({
                "type": "Maintenance Recharge",
                "amount": flt(job.recharge_amount, 2),
                "income_account": maintenance_account,
                "remarks": "{0} — {1}".format(job.name,
                                                job.issue or "Maintenance"),
                "source_doctype": "Maintenance Request",
                "source_name": job.name,
            })
            queued_recharges.add(job.name)
        for allocation in utility_allocations:
            if not (allocation.tenant == a.tenant and allocation.unit == a.unit):
                continue
            bill = utility_by_name.get(allocation.parent)
            snapshots.append({
                "type": "Utility Recovery",
                "amount": flt(allocation.amount, 2),
                "income_account": utility_account,
                "remarks": "{0} — {1} {2}".format(
                    allocation.parent,
                    (bill.utility_type if bill else "Utility"),
                    (bill.bill_no if bill else "bill")),
                "source_doctype": "Utility Bill Allocation",
                "source_name": allocation.name,
            })
            queued_utility.add(allocation.name)
        # Maintenance and utility recoveries are monthly obligations.  A
        # quarterly or annual rent schedule must not hold them until the next
        # rent cycle; create a recovery-only line when no rent falls due.
        if not window and not snapshots:
            continue
        amount = flt(agreed + sum(x["amount"] for x in snapshots), 2)
        variance = flt(amount - agreed, 2)
        if variance:
            variance_seen = True
        kinds = {x["type"] for x in snapshots}
        if kinds == {"Utility Recovery"}:
            reason = "Utility recovery for this period"
        elif kinds == {"Maintenance Recharge"}:
            reason = "Maintenance recharge for this period"
        elif snapshots:
            reason = "Recurring charges and recoveries for this period"
        else:
            reason = None
        run.append("lines", {
            "tenancy_agreement": a.name,
            "tenant": a.tenant,
            "unit": a.unit,
            "agreement_amount": agreed,
            "invoice_amount": amount,
            "variance": variance,
            "reason": reason if variance else None,
            "charge_snapshot": frappe.as_json(snapshots),
        })
        total += amount

    if not run.lines:
        frappe.throw(_("{0} has no rent due in that period.").format(building))

    run.total_amount = total
    run.has_variance = 1 if variance_seen else 0
    run.flags.ignore_mandatory = True
    run.insert(ignore_permissions=True)
    for job in queued_recharges:
        frappe.db.set_value("Maintenance Request", job, {
            "recharge_status": "Queued",
            "recharge_invoice_run": run.name,
        })
    for allocation in queued_utility:
        frappe.db.set_value("Utility Bill Allocation", allocation,
                            "invoice_run", run.name)
    return {"run": run.name, "lines": len(run.lines), "total": _kk(total)}


@frappe.whitelist()
def invoice_run(run):
    """A drafted run and its lines, for the screen that reviews it.

    build_invoice_run returns a count. The reviewer needs the lines
    themselves — what each agreement says, what the invoice would be, and
    where the two differ — because reading them is the whole point of a run
    existing before anything is issued.
    """
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Invoice Run", run)
    require_record_access(doc, "read")
    tenants = {}
    for t in {l.tenant for l in doc.lines if l.tenant}:
        tenants[t] = frappe.db.get_value("Customer", t, "customer_name") or t

    cancelled = set()
    invoice_names = [l.sales_invoice for l in doc.lines if l.sales_invoice]
    if invoice_names:
        cancelled = set(frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", invoice_names], "docstatus": 2},
            pluck="name",
        ))

    return {
        "run": doc.name,
        "building": doc.building,
        "period_start": str(doc.period_start),
        "period_end": str(doc.period_end),
        "status": doc.status,
        "total": _kk(doc.total_amount),
        "has_variance": 1 if doc.has_variance else 0,
        "variance_reason": doc.variance_reason or "",
        "cancelled_invoices": len(cancelled),
        "lines": [{
            "a": l.tenancy_agreement,
            "t": l.tenant,
            "tn": tenants.get(l.tenant, l.tenant),
            "u": l.unit,
            "agreed": _kk(l.agreement_amount),
            "amount": _kk(l.invoice_amount),
            "variance": _kk(l.variance),
            "reason": l.reason or "",
            "invoice": l.sales_invoice,
            "invoice_cancelled": 1 if l.sales_invoice in cancelled else 0,
            "charges": frappe.parse_json(l.charge_snapshot or "[]"),
        } for l in doc.lines],
    }


@frappe.whitelist()
def reopen_cancelled_invoice_run(run):
    """Return only cancelled lines of an issued run to GM review.

    This is the explicit recovery path for invoices cancelled before the
    Sales Invoice cancellation hook was installed, or if that hook was
    temporarily unavailable.  Live invoices remain linked and cannot be
    duplicated.
    """
    guard(MD, GM)
    doc = frappe.get_doc("Invoice Run", run)
    require_record_access(doc, "write")
    if doc.status != "Issued":
        frappe.throw(_("{0} is {1}; only an issued run can be reopened.").format(
            run, doc.status))

    reopened = 0
    for line in doc.lines:
        if not line.sales_invoice:
            continue
        if frappe.db.get_value("Sales Invoice", line.sales_invoice,
                               "docstatus") == 2:
            line.db_set("sales_invoice", None, update_modified=False)
            reopened += 1
    if not reopened:
        frappe.throw(_("{0} has no cancelled invoices to replace.").format(run))

    doc.status = "Pending GM"
    doc.approved_by = None
    doc.issued_on = None
    doc.save(ignore_permissions=True)
    return {"run": doc.name, "status": doc.status, "reopened": reopened}


@frappe.whitelist()
def submit_invoice_run(run):
    """Send a drafted run for approval."""
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Invoice Run", run)
    require_record_access(doc, "write")
    if doc.status != "Draft":
        frappe.throw(_("{0} is {1}.").format(run, doc.status))
    doc.status = "Pending GM"
    doc.save(ignore_permissions=True)
    return {"run": doc.name, "status": doc.status}


@frappe.whitelist()
def cancel_invoice_run(run, reason):
    """Cancel an unissued run and release every reserved recovery.

    Issued runs are corrected invoice-by-invoice so ERPNext can reverse their
    ledger entries.  This path is only for a draft that has posted nothing.
    """
    guard(MD, GM)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Cancelling an invoice run needs an audit reason."))
    doc = frappe.get_doc("Invoice Run", run)
    require_record_access(doc, "write")
    if doc.status not in ("Draft", "Pending GM"):
        frappe.throw(_("{0} is {1}; only an unissued run can be cancelled.")
                     .format(run, doc.status))
    if any((line.get("sales_invoice") if hasattr(line, "get")
            else getattr(line, "sales_invoice", None)) for line in doc.lines):
        frappe.throw(_("{0} already has an invoice; cancel that invoice through "
                       "the controlled correction workflow.").format(run))

    maintenance = frappe.get_all(
        "Maintenance Request",
        filters={"recharge_invoice_run": run,
                 "recharge_invoice": ["is", "not set"]},
        pluck="name")
    for name in maintenance:
        frappe.db.set_value("Maintenance Request", name, {
            "recharge_status": "Pending", "recharge_invoice_run": None,
        })
    allocations = frappe.get_all(
        "Utility Bill Allocation",
        filters={"invoice_run": run, "sales_invoice": ["is", "not set"]},
        pluck="name")
    for name in allocations:
        frappe.db.set_value("Utility Bill Allocation", name,
                            "invoice_run", None)

    doc.status = "Cancelled"
    doc.add_comment("Comment", _("Invoice run cancelled: {0}").format(reason))
    doc.save(ignore_permissions=True)
    return {"run": doc.name, "status": doc.status,
            "maintenance_released": len(maintenance),
            "utility_released": len(allocations)}


@frappe.whitelist()
def issue_invoice_run(run):
    """Approve the run and raise the invoices. This is the point of no return,
    so it is one transaction: every line becomes an invoice or none does."""
    guard(MD, GM)
    doc = frappe.get_doc("Invoice Run", run)
    require_record_access(doc, "write")
    if doc.status != "Pending GM":
        frappe.throw(_("{0} is {1} and cannot be issued.").format(
            run, doc.status))

    made = 0
    for line in doc.lines:
        if line.sales_invoice:
            continue
        si = _rent_invoice(doc, line)
        line.db_set("sales_invoice", si, update_modified=False)
        made += 1

    doc.status = "Issued"
    doc.approved_by = frappe.session.user
    doc.issued_on = frappe.utils.now()
    doc.save(ignore_permissions=True)
    return {"run": doc.name, "status": doc.status, "invoices": made}


def _rent_invoice(run, line):
    """One month of rent as a Sales Invoice. ERPNext posts it."""
    period = str(run.period_start)
    existing = frappe.db.get_value(
        "Sales Invoice",
        {"custom_rental_agreement": line.tenancy_agreement,
         "custom_billing_period": period,
         "docstatus": ["<", 2]}, "name")
    snapshots = frappe.parse_json(line.charge_snapshot or "[]")
    if existing:
        _mark_source_recharges(snapshots, run.name, existing)
        return existing
    item = _rent_item()
    items = []
    # A zero-rate rent item is not harmless in ERPNext: item-price resolution
    # can replace zero with the item's default selling rate. Recovery-only
    # invoices therefore omit rent completely instead of posting phantom rent.
    if flt(line.agreement_amount) > 0:
        items.append({
            "item_code": item,
            "item_name": f"Rent — {line.unit}",
            "description": (f"Rent for {line.unit}, "
                            f"{run.period_start} to {run.period_end}"),
            "qty": 1,
            "rate": flt(line.agreement_amount),
            "cost_center": _cost_center(run.building),
        })
    for charge in snapshots:
        items.append({
            "item_code": item,
            "item_name": charge.get("type") or "Tenancy charge",
            "description": charge.get("remarks") or charge.get("type"),
            "qty": 1,
            "rate": flt(charge.get("amount")),
            "income_account": charge.get("income_account"),
            "cost_center": _cost_center(run.building),
        })
    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": line.tenant,
        "company": run.company,
        # Without this ERPNext resets posting_date to today on save, which
        # puts it after the due date on any run for a month already gone and
        # refuses the invoice. A catch-up run could never be issued.
        "set_posting_time": 1,
        "posting_date": run.period_start,
        "due_date": add_days(run.period_start,
                             int(_settings().grace_days or 0)),
        "currency": "QAR",
        "cost_center": _cost_center(run.building),
        "custom_rental_agreement": line.tenancy_agreement,
        "custom_billing_period": period,
        "items": items,
    })
    si.flags.ignore_mandatory = True
    # on flags, not just on insert: submit() saves again and checks
    # permissions afresh, so a one-shot argument does not carry
    si.flags.ignore_permissions = True
    si.insert(ignore_permissions=True)
    si.submit()
    _mark_source_recharges(snapshots, run.name, si.name)
    return si.name


def _mark_source_recharges(snapshots, run_name, invoice):
    for charge in snapshots:
        source = charge.get("source_doctype")
        name = charge.get("source_name")
        if not name:
            continue
        if source == "Maintenance Request":
            queued_run = frappe.db.get_value(
                "Maintenance Request", name, "recharge_invoice_run")
            if queued_run != run_name:
                frappe.throw(_(
                    "Maintenance recharge {0} is reserved by another invoice "
                    "run.").format(name))
            frappe.db.set_value("Maintenance Request", name, {
                "recharge_status": "Invoiced",
                "recharge_invoice": invoice,
            })
        elif source == "Utility Bill Allocation":
            queued_run = frappe.db.get_value(
                "Utility Bill Allocation", name, "invoice_run")
            if queued_run != run_name:
                frappe.throw(_(
                    "Utility allocation {0} is reserved by another invoice "
                    "run.").format(name))
            parent = frappe.db.get_value(
                "Utility Bill Allocation", name, "parent")
            frappe.db.set_value("Utility Bill Allocation", name,
                                "sales_invoice", invoice)
            if parent and not frappe.db.count(
                    "Utility Bill Allocation",
                    filters={"parent": parent,
                             "sales_invoice": ["is", "not set"]}):
                frappe.db.set_value("Utility Bill", parent,
                                    "status", "Recovered")


@frappe.whitelist()
def cancel_run_invoice(invoice, reason):
    """Cancel one wholly-unpaid invoice created by an Invoice Run.

    This deliberately is not a general invoice-edit endpoint.  ERPNext owns
    the reversal, and the Sales Invoice cancellation hook reopens the run line
    and returns any maintenance recharge on it to ``Queued``.  Restricting the
    endpoint to run invoices prevents the shell from cancelling unrelated
    accounting documents through an identifier alone.
    """
    guard(MD, GM)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("An invoice cancellation needs an audit reason."))

    si = frappe.get_doc("Sales Invoice", invoice)
    if si.docstatus != 1:
        state = "cancelled" if si.docstatus == 2 else "draft"
        frappe.throw(_("{0} is {1}, not a submitted invoice.").format(
            invoice, state))

    line = frappe.db.get_value(
        "Invoice Run Line",
        {"sales_invoice": invoice, "parenttype": "Invoice Run"},
        ["name", "parent", "charge_snapshot"], as_dict=True,
    )
    if not line or not line.parent:
        frappe.throw(_("{0} was not raised by an Invoice Run.").format(invoice))
    run = frappe.get_doc("Invoice Run", line.parent)
    require_record_access(run, "write")

    grand_total = flt(si.grand_total)
    outstanding = flt(si.outstanding_amount)
    if abs(grand_total - outstanding) >= 0.005:
        frappe.throw(_(
            "{0} has payments or credits allocated. Reverse those first; "
            "only a wholly unpaid invoice can be cancelled here."
        ).format(invoice))

    jobs = [
        charge.get("source_name")
        for charge in frappe.parse_json(line.charge_snapshot or "[]")
        if charge.get("source_doctype") == "Maintenance Request"
        and charge.get("source_name")
    ]
    si.add_comment("Comment", "Invoice cancelled: {0}".format(reason))
    si.flags.ignore_permissions = True
    si.cancel()

    return {
        "invoice": si.name,
        "status": "Cancelled",
        "run": run.name,
        "run_status": frappe.db.get_value("Invoice Run", run.name, "status"),
        "maintenance": [{
            "job": job,
            "status": frappe.db.get_value(
                "Maintenance Request", job, "recharge_status"),
        } for job in jobs],
    }


def _rent_item():
    name = "Rent"
    if frappe.db.exists("Item", name):
        return name
    group = (frappe.db.get_value("Item Group", {"item_group_name": "Services"},
                                 "name")
             or frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
    doc = frappe.get_doc({
        "doctype": "Item", "item_code": name, "item_name": "Rent",
        "item_group": group, "stock_uom": "Nos",
        "is_stock_item": 0, "is_sales_item": 1, "is_purchase_item": 0,
    })
    doc.flags.ignore_mandatory = True
    return doc.insert(ignore_permissions=True).name


def _cost_center(building):
    return frappe.db.get_value("Building", building, "cost_center") or None


# ------------------------------------------------------ head-lease accruals

def _head_lease_accrual_window(lease, period_start):
    """Monthly economic accrual, independent of the landlord payment cycle."""
    period_start = getdate(period_start).replace(day=1)
    period_end = _month_end(period_start)
    lease_start, lease_end = getdate(lease.start_date), getdate(lease.end_date)
    billable_start = getdate(add_days(lease_start,
                                      int(lease.rent_free_days or 0)))
    start = max(period_start, billable_start)
    end = min(period_end, lease_end)
    return (start, end) if start <= end else None


def _head_lease_expense_account(company):
    for label in ("Head Lease Rent",):
        account = frappe.db.get_value(
            "Account", {"company": company, "account_name": label,
                        "is_group": 0}, "name")
        if account:
            return account
    frappe.throw(_(
        "Configure the Head Lease Rent expense account before generating "
        "landlord accruals."))


def _landlord_rent_item():
    name = "Landlord Rent"
    if frappe.db.exists("Item", name):
        return name
    group = (frappe.db.get_value("Item Group", {"item_group_name": "Services"},
                                 "name")
             or frappe.db.get_value("Item Group", {"is_group": 0}, "name"))
    doc = frappe.get_doc({
        "doctype": "Item", "item_code": name, "item_name": name,
        "item_group": group, "stock_uom": "Nos",
        "is_stock_item": 0, "is_sales_item": 0, "is_purchase_item": 1,
    })
    doc.flags.ignore_mandatory = True
    return doc.insert(ignore_permissions=True).name


@frappe.whitelist()
def build_head_lease_payable(building, period_start=None):
    """Create one draft monthly landlord accrual for a Building.

    Payment frequency belongs to the payment schedule. Expense recognition is
    monthly under the launch accrual policy, including calendar-day proration
    and rent-free days. This endpoint never submits or posts the invoice.
    """
    guard(MD, GM, ACC)
    require_building_access(building)
    start = getdate(period_start or today()).replace(day=1)
    period = str(start)
    leases = frappe.get_all(
        "Head Lease",
        filters={"building": building,
                 "status": ["in", ("Active", "Expiring")]},
        fields=["name", "landlord", "company", "start_date", "end_date",
                "monthly_rent", "annual_rent", "rent_free_days",
                "cost_center"])
    eligible = [(lease, _head_lease_accrual_window(lease, start))
                for lease in leases]
    eligible = [(lease, window) for lease, window in eligible if window]
    if not eligible:
        frappe.throw(_("{0} has no Head Lease cost due in that period.").format(
            building))
    if len(eligible) != 1:
        frappe.throw(_(
            "{0} has multiple live Head Leases in that period; resolve the "
            "overlap before generating payables.").format(building))

    lease, window = eligible[0]
    existing = frappe.db.get_value(
        "Purchase Invoice",
        {"custom_landlord_contract": lease.name,
         "custom_billing_period": period,
         "docstatus": ["<", 2]}, ["name", "grand_total", "docstatus"], as_dict=True)
    if existing:
        return {"invoice": existing.name, "created": False,
                "status": "Submitted" if existing.docstatus == 1 else "Draft",
                "amount": _kk(existing.grand_total),
                "head_lease": lease.name}

    company = lease.company or _company()
    monthly = flt(lease.monthly_rent or flt(lease.annual_rent) / 12, 2)
    amount = _prorated_monthly(monthly, *window)
    if amount <= 0:
        frappe.throw(_("The Head Lease accrual amount must be positive."))
    cost_center = lease.cost_center or _cost_center(building)
    pi = frappe.get_doc({
        "doctype": "Purchase Invoice",
        "supplier": lease.landlord,
        "company": company,
        "set_posting_time": 1,
        "posting_date": start,
        "due_date": _month_end(start),
        "bill_no": "DBR-{0}-{1}".format(lease.name, start.strftime("%Y-%m")),
        "bill_date": start,
        "currency": "QAR",
        "custom_landlord_contract": lease.name,
        "custom_billing_period": period,
        "remarks": ("Monthly Head Lease accrual for {0}: {1} to {2}. "
                    "Payment remains controlled by the lease schedule.").format(
                        building, window[0], window[1]),
        "items": [{
            "item_code": _landlord_rent_item(),
            "item_name": "Landlord Rent",
            "description": "Head Lease rent for {0}, {1} to {2}".format(
                building, window[0], window[1]),
            "qty": 1,
            "rate": amount,
            "expense_account": _head_lease_expense_account(company),
            "cost_center": cost_center,
        }],
    })
    pi.flags.ignore_mandatory = True
    pi.insert(ignore_permissions=True)
    return {"invoice": pi.name, "created": True, "status": "Draft",
            "amount": _kk(amount), "head_lease": lease.name}


@frappe.whitelist()
def issue_head_lease_payable(invoice):
    """GM/MD approval boundary for a generated landlord accrual."""
    guard(MD, GM)
    pi = frappe.get_doc("Purchase Invoice", invoice)
    lease_name = pi.get("custom_landlord_contract")
    if not lease_name:
        frappe.throw(_("{0} is not a generated Head Lease payable.").format(
            invoice))
    lease = frappe.get_doc("Head Lease", lease_name)
    require_record_access(lease, "read")
    require_building_access(lease.building)
    if pi.supplier != lease.landlord or pi.company != (lease.company or _company()):
        frappe.throw(_("The landlord bill does not match its Head Lease."))
    if pi.docstatus == 1:
        return {"invoice": pi.name, "status": "Submitted"}
    if pi.docstatus != 0:
        frappe.throw(_("{0} is cancelled and cannot be issued.").format(invoice))
    pi.flags.ignore_permissions = True
    pi.submit()
    return {"invoice": pi.name, "status": "Submitted"}


@frappe.whitelist()
def landlord_payments():
    """Draft and outstanding Head Lease bills with their controlled building."""
    guard(MD, GM, ACC)
    rows = []
    while True:
        page = frappe.get_all(
            "Purchase Invoice",
            filters={"docstatus": ["in", [0, 1]],
                     "custom_landlord_contract": ["is", "set"]},
            fields=["name", "supplier", "company", "docstatus",
                    "grand_total", "outstanding_amount",
                    "due_date", "custom_landlord_contract"],
            order_by="due_date asc, creation asc", limit_start=len(rows),
            limit_page_length=1000)
        rows.extend(page)
        if len(page) < 1000:
            break
    rows = [r for r in rows if r.custom_landlord_contract]
    lease_ids = list({r.custom_landlord_contract for r in rows
                      if r.custom_landlord_contract})
    leases = ({l.name: l for l in frappe.get_all(
        "Head Lease", filters={"name": ["in", lease_ids]},
        fields=["name", "building", "landlord", "company"])}
        if lease_ids else {})
    scope = allowed_buildings()
    buildings = {b.name: b.building_name for b in frappe.get_all(
        "Building", filters={"name": ["in", list({
            l.building for l in leases.values() if l.building})]},
        fields=["name", "building_name"])} if leases else {}
    suppliers = {s.name: s.supplier_name for s in frappe.get_all(
        "Supplier", filters={"name": ["in", list({
            l.landlord for l in leases.values() if l.landlord})]},
        fields=["name", "supplier_name"])} if leases else {}
    out = []
    for r in rows:
        lease = leases.get(r.custom_landlord_contract)
        if (not lease or r.supplier != lease.landlord
                or r.company != (lease.company or _company())
                or (scope is not None and lease.building not in scope)):
            continue
        amount = flt(r.grand_total if r.docstatus == 0
                     else r.outstanding_amount, 2)
        if amount <= 0:
            continue
        out.append({"invoice": r.name, "head_lease": lease.name,
                    "building": lease.building,
                    "building_name": buildings.get(lease.building) or lease.building,
                    "landlord": lease.landlord,
                    "landlord_name": suppliers.get(lease.landlord) or lease.landlord,
                    "amount": amount,
                    "status": "Draft" if r.docstatus == 0 else "Outstanding",
                    "due_date": str(r.due_date or "")})
    # A landlord is visible even when no monthly bill has been generated.
    # Outstanding means submitted unpaid bills, not the monthly rent estimate.
    represented = {(r["building"], r["landlord"]) for r in out}
    all_buildings = frappe.get_all("Building", fields=["name", "building_name", "landlord"])
    for b in all_buildings:
        if not b.landlord or (scope is not None and b.name not in scope):
            continue
        if (b.name, b.landlord) not in represented:
            out.append({"invoice": "", "head_lease": "", "building": b.name,
                "building_name": b.building_name or b.name,
                "landlord": b.landlord,
                "landlord_name": suppliers.get(b.landlord) or
                    frappe.db.get_value("Supplier", b.landlord, "supplier_name") or b.landlord,
                "amount": 0, "status": "No bill outstanding", "due_date": ""})
        represented.add((b.name, b.landlord))
    for lease in frappe.get_all("Head Lease", fields=["name", "building", "landlord"]):
        if not lease.landlord or (scope is not None and lease.building not in scope):
            continue
        if (lease.building, lease.landlord) not in represented:
            out.append({"invoice": "", "head_lease": lease.name,
                "building": lease.building,
                "building_name": buildings.get(lease.building) or
                    frappe.db.get_value("Building", lease.building, "building_name") or lease.building,
                "landlord": lease.landlord,
                "landlord_name": suppliers.get(lease.landlord) or
                    frappe.db.get_value("Supplier", lease.landlord, "supplier_name") or lease.landlord,
                "amount": 0, "status": "No bill outstanding", "due_date": ""})
        represented.add((lease.building, lease.landlord))
    # Landlords that have no building yet should still appear in the register.
    if scope is None:
        for supplier in frappe.get_all("Supplier", filters={"db_is_landlord": 1},
                                       fields=["name", "supplier_name"]):
            if not any(r["landlord"] == supplier.name for r in out):
                out.append({"invoice": "", "head_lease": "", "building": "",
                    "building_name": "—", "landlord": supplier.name,
                    "landlord_name": supplier.supplier_name or supplier.name,
                    "amount": 0, "status": "No bill outstanding", "due_date": ""})
    return {"rows": out}


@frappe.whitelist()
def record_landlord_payment(payload):
    """Settle a specific approved Head Lease bill once via Payment Entry."""
    guard(MD, ACC)
    data = frappe.parse_json(payload)
    invoice = data.get("invoice")
    if not invoice:
        frappe.throw(_("Choose a landlord bill to pay."))
    frappe.db.sql("SELECT name FROM `tabPurchase Invoice` WHERE name = %s "
                  "FOR UPDATE", (invoice,))
    pi = frappe.get_doc("Purchase Invoice", invoice)
    lease_name = pi.get("custom_landlord_contract")
    if pi.docstatus != 1 or not lease_name or flt(pi.outstanding_amount) <= 0:
        frappe.throw(_("This landlord bill is not issued and outstanding."))
    lease = frappe.get_doc("Head Lease", lease_name)
    require_building_access(lease.building)
    if (pi.supplier != lease.landlord or pi.company != (lease.company or _company())
            or pi.company != _company()):
        frappe.throw(_("The landlord bill does not match its Head Lease."))
    amount = flt(data.get("amount"), 2)
    if amount <= 0 or amount > flt(pi.outstanding_amount, 2):
        frappe.throw(_("Amount must be greater than zero and no more than the bill balance."))
    mode = data.get("mode")
    if mode not in ("Bank transfer", "Cash", "Cheque"):
        frappe.throw(_("Choose the landlord payment method."))
    bank = data.get("bank_account")
    if bank == "Other bank":
        bank = str(data.get("other_bank") or "").strip()
    if mode != "Cash":
        account = (frappe.db.get_value("Bank Account", {
            "name": bank, "company": pi.company,
            "is_company_account": 1}, "account") if bank else None)
        if not account or _paid_to(bank, pi.company) != account or \
                frappe.db.get_value("Account", account, "account_type") != "Bank":
            frappe.throw(_("Choose a configured company bank account for this payment. Add an other bank to Bank Accounts first if needed."))
    reference = (data.get("reference") or "").strip()
    if not reference:
        request_id = str(data.get("request_id") or "")
        if request_id and (len(request_id.replace("-", "")) < 12 or
                           not all(c in "0123456789abcdefABCDEF-" for c in request_id)):
            frappe.throw(_("Invalid payment request identifier."))
        reference = "DBR-" + (request_id.replace("-", "").upper()[:24]
                              if request_id else secrets.token_hex(12).upper())
    on = getdate(data.get("on") or today())
    cheque = None
    if mode == "Cheque":
        number = str(data.get("cheque_no") or "").strip()
        cheque_date = data.get("cheque_date")
        if not number or not cheque_date:
            frappe.throw(_("Enter the outgoing cheque number and date."))
        if frappe.db.exists("Cheque", {"direction": "Outgoing", "party": pi.supplier,
                                       "cheque_no": number, "status": ["!=", "Cancelled"]}):
            frappe.throw(_("This landlord cheque number is already recorded."))
        bank_name = frappe.db.get_value("Bank Account", bank, "bank") or bank
        cheque = frappe.get_doc({"doctype": "Cheque", "direction": "Outgoing",
            "party_type": "Supplier", "party": pi.supplier, "company": pi.company,
            "status": "Issued", "cheque_no": number, "cheque_date": cheque_date,
            "bank": bank_name, "bank_account": bank, "amount": amount,
            "payment_entry": None,
            "building": lease.building, "head_lease": lease.name,
            "purchase_invoice": pi.name, "purpose": "Head-lease rent"})
        cheque.insert(ignore_permissions=True)
        reference = cheque.name
    prior = frappe.get_all(
        "Payment Entry", filters={"payment_type": "Pay", "party": pi.supplier,
                                  "posting_date": str(on), "reference_no": reference,
                                  "docstatus": 1},
        fields=["name", "paid_amount", "mode_of_payment"])
    if any(abs(flt(row.paid_amount) - amount) < 0.005
           and row.mode_of_payment == mode for row in prior):
        frappe.throw(_("This landlord payment is already recorded."))
    payment, applied, unused = _supplier_payment(
        pi.supplier, amount, on, bank_account=bank, mode=mode,
        reference=reference, invoice=pi.name, head_lease=lease.name)
    if unused or not applied or applied[0][0] != pi.name:
        frappe.throw(_("Payment could not be allocated to the selected landlord bill."))
    if cheque:
        cheque.payment_entry = payment
        cheque.save(ignore_permissions=True)
    return {"payment_entry": payment, "invoice": pi.name,
            "building": lease.building, "amount": flt(amount, 2),
            "cheque": cheque.name if cheque else None}


# ------------------------------------------------------------------- receipts

@frappe.whitelist()
def record_receipt(payload):
    """Money received against a tenant, allocated oldest invoice first.

    Allocation is not a judgement call. The oldest debt clears first, which is
    what the ageing report assumes and what a tenant disputing a balance will
    be shown.
    """
    guard(MD, ACC)
    data = frappe.parse_json(payload)
    tenant = data.get("tenant")
    amount = flt(data.get("amount"))
    if not tenant or amount <= 0:
        frappe.throw(_("A receipt needs a tenant and an amount."))
    require_tenant_access(tenant)
    mode = data.get("mode")
    if mode not in ("Cash", "Bank transfer", "Bank Transfer", "Card", "Cheque"):
        frappe.throw(_("Choose how the payment was received."))
    if mode == "Cheque":
        frappe.throw(_("Receive a cheque through Record payment, then deposit it in a batch. Its receipt posts after the matched bank statement."))

    reference = (data.get("reference") or "").strip()
    # Some cash collections have no external reference. Give the Payment Entry
    # a distinct internal identifier; never pretend it is a bank reference.
    if not reference:
        request_id = str(data.get("request_id") or "")
        if request_id and (len(request_id.replace("-", "")) < 12 or
                           not all(c in "0123456789abcdefABCDEF-" for c in request_id)):
            frappe.throw(_("Invalid receipt request identifier."))
        reference = "DBR-" + (request_id.replace("-", "").upper()[:24]
                              if request_id else secrets.token_hex(12).upper())
    # Lock the customer's row until the request commits. A second submission
    # for the same tenant must recheck after the first transaction commits.
    frappe.db.sql("SELECT name FROM `tabCustomer` WHERE name = %s FOR UPDATE",
                  (tenant,))
    on = getdate(data.get("on") or today())
    prior = frappe.get_all(
        "Payment Entry",
        filters={"payment_type": "Receive", "party": tenant,
                 "posting_date": str(on), "reference_no": reference,
                 "docstatus": 1},
        fields=["name", "paid_amount", "mode_of_payment"])
    if any(abs(flt(row.paid_amount) - amount) < 0.005
           and row.mode_of_payment == mode
           for row in prior):
        frappe.throw(_("This tenant already has a submitted receipt with the "
                       "same date, reference, amount and method. Cancel the "
                       "incorrect receipt before recording a replacement."))

    pe, applied, on_account = _receipt(
        tenant, amount, on,
        data.get("bank_account"), mode=mode,
        reference=reference, invoice=data.get("invoice"),
        collector=(frappe.db.get_value("User", frappe.session.user, "full_name")
                   or frappe.session.user)
        if data.get("mode") == "Cash" else None)
    return {"payment_entry": pe, "allocated": _kk(amount),
            "applied": [a[0] for a in applied],
            "applied_detail": [{"invoice": a[0], "amount": _kk(a[1])}
                               for a in applied],
            "on_account": _kk(on_account)}


def _paid_to(value, company):
    """The ledger account a receipt lands in.

    A Bank Account and an Account are two different doctypes and Payment
    Entry.paid_to links to the second. Everywhere else in this app a "bank
    account" means the first, so handing that name straight to paid_to gives
    "Account: ... is not permitted under Payment Entry" and no receipt can
    ever be posted. Resolve it here rather than at each of the four call
    sites, and accept either kind so a caller passing a ledger account
    directly still works.
    """
    if value:
        gl = frappe.db.get_value("Bank Account", value, "account")
        candidate = gl or (value if frappe.db.exists("Account", value)
                           else None)
        # A Bank Account mapping is configuration, not proof that the linked
        # ledger is actually cash.  Accepting an untyped asset here makes the
        # receipt post successfully while disappearing from every cash-flow
        # report.  Fail closed so the chart can be repaired explicitly.
        return _operational_money_account(candidate, company)

    candidate = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank",
                    "is_group": 0, "disabled": 0}, "name")
    return (_operational_money_account(candidate, company)
            or _cash_account(company))


def _operational_money_account(account, company):
    """Return a real cash/bank leaf or ``None`` for unsafe configuration."""
    if not account:
        return None
    details = frappe.db.get_value(
        "Account", account,
        ["company", "root_type", "account_type", "is_group", "disabled",
         "account_name"], as_dict=True)
    if (details and details.company == company
            and details.root_type == "Asset"
            and details.account_type in ("Bank", "Cash")
            and not details.is_group and not details.disabled
            and details.account_name != "Historical Cutover Control"):
        return account
    return None


def _cash_account(company):
    """Resolve an operational cash ledger without ever selecting a control.

    Historical Cutover Control is deliberately tagged as Cash so historical
    imports can balance, which makes a bare ``account_type=Cash`` lookup
    unsafe for real receipts and refunds.  Operational cash must have an
    explicit cash name or a validated Mode of Payment mapping.
    """
    for label in ("Cash", "Cash in Hand", "Cash Clearing"):
        account = frappe.db.get_value("Account", {
            "company": company, "account_name": label, "is_group": 0,
            "disabled": 0,
        }, "name")
        if (account and _operational_money_account(account, company)
                and frappe.db.get_value("Account", account, "account_type")
                == "Cash"):
            return account

    mapped = frappe.db.get_value("Mode of Payment Account", {
        "parent": "Cash", "company": company,
    }, "default_account")
    if not mapped:
        return None
    details = frappe.db.get_value("Account", mapped,
                                  ["account_type", "account_name"],
                                  as_dict=True)
    if (details and _operational_money_account(mapped, company)
            and details.account_type == "Cash"
            and details.account_name != "Petty Cash"):
        return mapped
    return None


def _receipt(customer, amount, on, bank_account=None, mode=None,
             reference=None, invoice=None, collector=None):
    """Post a receipt and say where the money went.

    Oldest-first remains the rule, because that is what the ageing report
    assumes and what a tenant disputing a balance is shown. A named invoice is
    the one exception, and it is a deliberate one: a tenant who pays a
    specific invoice and is credited against an older one will dispute it. The
    named invoice is settled first and anything left over then falls to the
    oldest, so the exception never becomes a way to leave old debt hidden.
    """
    company = _company()
    # A cash collection is held in the cash ledger until a deposit moves it to
    # the bank. A deposit batch supplies an explicit bank account: its cash
    # lines are already banked, so keep that destination.
    account = (_cash_account(company)
               if mode == "Cash" and not bank_account
               else _paid_to(bank_account or _settings().default_bank_account,
                             company))
    if not account:
        frappe.throw(_(
            "No valid cash or bank ledger is configured for this receipt. "
            "Configure the Cash mode account or the Default Bank Account."))

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.company = company
    pe.posting_date = on
    pe.party_type = "Customer"
    pe.party = customer
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.paid_to = account
    pe.mode_of_payment = mode or "Cheque"
    pe.reference_no = reference
    pe.reference_date = on
    if collector:
        # ERPNext generates its own payment summary during validation unless
        # this flag is set. Preserve the identity of the cash collector.
        pe.custom_remarks = 1
        pe.remarks = _("Cash collected by {0}.").format(collector)

    open_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1,
                 "outstanding_amount": [">", 0]},
        fields=["name", "outstanding_amount", "posting_date"],
        order_by="posting_date asc")

    if invoice:
        # It has to be this customer's, and it has to be open. A receipt
        # pointed at somebody else's invoice is not a typo worth honouring.
        named = [si for si in open_invoices if si.name == invoice]
        if not named:
            frappe.throw(_("{0} is not an open invoice for {1}.").format(
                invoice, customer))
        open_invoices = named + [si for si in open_invoices
                                 if si.name != invoice]

    left = amount
    applied = []
    for si in open_invoices:
        if left <= 0:
            break
        take = min(left, flt(si.outstanding_amount))
        pe.append("references", {
            "reference_doctype": "Sales Invoice",
            "reference_name": si.name,
            "allocated_amount": take,
        })
        applied.append((si.name, take))
        left -= take

    if left > 0:
        pe.unallocated_amount = left

    pe.flags.ignore_mandatory = True
    # The app decides who may clear a cheque; ERPNext should not then ask
    # whether that person holds the Payment Entry role as well. Without this
    # every receipt fails on submit for anyone but a System Manager.
    pe.flags.ignore_permissions = True
    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe.name, applied, left


def _supplier_payment(supplier, amount, on, bank_account=None, mode=None,
                      reference=None, invoice=None, head_lease=None):
    """Post an outgoing supplier payment, allocating the intended bill first.

    A head-lease cheque is restricted to bills for that head lease. Other
    supplier cheques settle the named bill first, then the oldest open bills.
    Any excess stays unallocated on the Payment Entry for review.
    """
    if amount <= 0:
        frappe.throw(_("A supplier payment amount must be greater than zero."))
    company = _company()
    account = (_cash_account(company) if mode == "Cash" else
               _paid_to(bank_account or _settings().default_bank_account,
                        company))
    if not account:
        frappe.throw(_(
            "No bank ledger is configured. Set the Default Bank Account in "
            "DBR Settings or pass a valid Bank Account."))

    filters = {"supplier": supplier, "docstatus": 1,
               "outstanding_amount": [">", 0]}
    if head_lease:
        filters["custom_landlord_contract"] = head_lease
    open_invoices = frappe.get_all(
        "Purchase Invoice", filters=filters,
        fields=["name", "outstanding_amount", "posting_date"],
        order_by="posting_date asc")
    if invoice:
        named = [pi for pi in open_invoices if pi.name == invoice]
        if not named:
            frappe.throw(_("{0} is not an open bill for {1}.").format(
                invoice, supplier))
        open_invoices = named + [pi for pi in open_invoices
                                 if pi.name != invoice]

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Pay"
    pe.company = company
    pe.posting_date = on
    pe.party_type = "Supplier"
    pe.party = supplier
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.paid_from = account
    pe.mode_of_payment = mode or "Cheque"
    pe.reference_no = reference
    pe.reference_date = on

    left, applied = amount, []
    for pi in open_invoices:
        if left <= 0:
            break
        take = min(left, flt(pi.outstanding_amount))
        pe.append("references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": pi.name,
            "allocated_amount": take,
        })
        applied.append((pi.name, take))
        left -= take
    if left > 0:
        pe.unallocated_amount = left
    pe.flags.ignore_mandatory = True
    pe.flags.ignore_permissions = True
    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe.name, applied, left


# ------------------------------------------------------------- deposit batches

def _depositable_cash_account(account, company):
    details = frappe.db.get_value("Account", account,
                                  ["account_type", "account_name"],
                                  as_dict=True)
    return bool(details and details.account_type == "Cash"
                and details.account_name != "Petty Cash"
                and _operational_money_account(account, company))

def _receipt_unit(pe):
    """Use the invoice recorded on the receipt; never guess among units."""
    invoice_names = [r.reference_name for r in pe.references or []
                     if r.reference_doctype == "Sales Invoice"
                     and r.reference_name]
    units = set()
    for name in invoice_names:
        agreement = frappe.db.get_value(
            "Sales Invoice", name, "custom_rental_agreement")
        if agreement:
            unit = frappe.db.get_value("Tenancy Agreement", agreement, "unit")
            if unit:
                units.add(unit)
    if not invoice_names:
        units = set(frappe.get_all("Tenancy Agreement",
                                   filters={"tenant": pe.party}, pluck="unit"))
        units.discard(None)
    return next(iter(units)) if len(units) == 1 else None


@frappe.whitelist()
def deposit_candidates():
    """Posted cash receipts and received cheques awaiting a deposit."""
    guard(MD, ACC)
    company = _company()
    bank_rows = frappe.get_all(
        "Bank Account", filters={"company": company, "is_company_account": 1},
        fields=["name", "account", "account_name"], order_by="account_name")
    banks = [{"id": b.name, "label": b.account_name or b.name}
             for b in bank_rows if _paid_to(b.name, company)
             and frappe.db.get_value("Account", b.account, "account_type") == "Bank"]
    cash = []
    skipped = 0
    scope = allowed_buildings()
    for r in frappe.get_all(
            "Payment Entry",
            filters={"payment_type": "Receive", "docstatus": 1,
                     "mode_of_payment": "Cash"},
            fields=["name", "party", "paid_amount", "paid_to",
                    "posting_date", "reference_no", "owner"],
            order_by="posting_date desc, creation desc", limit=1000):
        if not _depositable_cash_account(r.paid_to, company):
            continue
        existing = frappe.db.get_value("Deposit Batch Line",
                                       {"payment_entry": r.name}, "parent")
        if existing and frappe.db.get_value("Deposit Batch", existing, "status") \
                != "Cancelled":
            continue
        pe = frappe.get_doc("Payment Entry", r.name)
        unit = _receipt_unit(pe)
        if not unit:
            if scope is None:
                skipped += 1  # Never reveal another scope's receipt count.
            continue
        building = frappe.db.get_value("Unit", unit, "building")
        if scope is not None and building not in scope:
            continue
        cash.append({"id": r.name, "tenant": r.party,
                     "name": frappe.db.get_value("Customer", r.party,
                                                 "customer_name") or r.party,
                     "unit": unit, "building": building,
                     "amount": _kk(r.paid_amount), "date": str(r.posting_date),
                     "reference": r.reference_no or "", "by": r.owner})
    cheques = []
    for c in frappe.get_all("Cheque",
            filters={"direction": "Incoming", "status": "Received",
                     "company": company},
            fields=["name", "party", "unit", "building", "amount",
                    "cheque_no", "cheque_date", "bank", "deposit_batch"],
            order_by="creation desc", limit_page_length=1000):
        existing = frappe.db.get_value("Deposit Batch Line", {"cheque": c.name}, "parent")
        if existing and frappe.db.get_value("Deposit Batch", existing, "status") != "Cancelled":
            continue
        building = c.building or (frappe.db.get_value("Unit", c.unit, "building") if c.unit else None)
        if not c.unit or not building or (scope is not None and building not in scope):
            continue
        cheques.append({"id": c.name, "tenant": c.party,
            "name": frappe.db.get_value("Customer", c.party, "customer_name") or c.party,
            "unit": c.unit, "building": building, "amount": _kk(c.amount),
            "date": str(c.cheque_date or ""), "number": c.cheque_no,
            "bank": c.bank or ""})
    return {"cash": cash, "cheques": cheques, "banks": banks,
            "unresolved": skipped}

@frappe.whitelist()
def create_deposit_batch(payload):
    """Posted cash receipts and received cheques going to the bank as one slip.

    Three quarters of what lands in the bank arrives without a payer name on
    it. Matching on the payer is therefore not available, and this is the
    replacement: the slip is captured here before it goes in, so the statement
    line can be matched to the slip rather than to a name that is not there.
    """
    guard(MD, ACC)
    data = frappe.parse_json(payload)
    lines = data.get("lines") or []
    if not lines:
        frappe.throw(_("A deposit needs at least one line."))
    bank_account = data.get("bank_account")
    if not bank_account or not frappe.db.exists("Bank Account", {
            "name": bank_account, "company": _company(), "is_company_account": 1}) or \
            not _paid_to(bank_account, _company()) or \
            frappe.db.get_value("Account", _paid_to(bank_account, _company()),
                                "account_type") != "Bank":
        frappe.throw(_("Choose a valid company Bank Account for the deposit."))

    seen_receipts = set()
    seen_cheques = set()
    checked_lines = []
    for line in lines:
        payment_type = line.get("type") or "Cash"
        if payment_type == "Cheque":
            name = line.get("cheque")
            if not name or name in seen_cheques:
                frappe.throw(_("Choose each received cheque only once."))
            if not frappe.db.exists("Cheque", name):
                frappe.throw(_("Cheque {0} does not exist.").format(name))
            seen_cheques.add(name)
            frappe.db.sql("SELECT name FROM `tabCheque` WHERE name = %s FOR UPDATE", (name,))
            cheque = frappe.get_doc("Cheque", name)
            require_record_access(cheque, "read")
            if (cheque.direction != "Incoming" or cheque.status != "Received"
                    or cheque.company != _company() or not cheque.unit
                    or not cheque.building or
                    frappe.db.get_value("Unit", cheque.unit, "building") != cheque.building):
                frappe.throw(_("{0} is not a received tenant cheque with a unit.").format(name))
            require_building_access(cheque.building)
            previous = frappe.db.get_value("Deposit Batch Line", {"cheque": name}, "parent")
            if previous and frappe.db.get_value("Deposit Batch", previous, "status") != "Cancelled":
                frappe.throw(_("{0} is already in deposit batch {1}.").format(name, previous))
            checked_lines.append({"type": "Cheque", "cheque": name,
                "tenant": cheque.party, "unit": cheque.unit,
                "amount": flt(cheque.amount), "slip_no": cheque.cheque_no})
            continue
        if payment_type != "Cash" or line.get("cheque"):
            frappe.throw(_("Choose a posted cash receipt or a received cheque."))

        checked = dict(line)
        receipt_name = line.get("payment_entry")
        if not receipt_name or receipt_name in seen_receipts:
            frappe.throw(_("Choose each posted cash receipt only once."))
        seen_receipts.add(receipt_name)
        # Serialise competing batch creations against the same receipt.
        frappe.db.sql("SELECT name FROM `tabPayment Entry` WHERE name = %s "
                      "FOR UPDATE", (receipt_name,))
        pe = frappe.get_doc("Payment Entry", receipt_name)
        require_tenant_access(pe.party)
        if (pe.docstatus != 1 or pe.payment_type != "Receive"
                or pe.mode_of_payment != "Cash"
                or not _depositable_cash_account(pe.paid_to, _company())):
            frappe.throw(_("{0} is not a posted cash receipt.").format(
                receipt_name))
        unit = _receipt_unit(pe)
        if not unit:
            frappe.throw(_("{0} has no unambiguous unit on its receipt.")
                         .format(receipt_name))
        previous = frappe.db.get_value("Deposit Batch Line",
                                       {"payment_entry": receipt_name},
                                       "parent")
        if previous and frappe.db.get_value("Deposit Batch", previous,
                                            "status") != "Cancelled":
            frappe.throw(_("{0} is already in deposit batch {1}.").format(
                receipt_name, previous))
        checked.update({"tenant": pe.party, "unit": unit,
                        "amount": flt(pe.paid_amount),
                        "slip_no": pe.reference_no,
                        "cheque": None})

        if checked.get("unit"):
            require_building_access(frappe.db.get_value(
                "Unit", checked.get("unit"), "building"))
        elif checked.get("tenant"):
            require_tenant_access(checked.get("tenant"))
        checked["type"] = payment_type
        checked_lines.append(checked)

    doc = frappe.get_doc({
        "doctype": "Deposit Batch",
        "deposit_date": data.get("date") or today(),
        "bank_account": bank_account,
        "status": "Draft",
        "company": _company(),
        "slip_no": data.get("slip_no"),
        "prepared_by": frappe.session.user,
    })

    total = 0
    for l in checked_lines:
        amount = flt(l.get("amount"))
        if amount <= 0:
            frappe.throw(_("Every deposit line needs an amount greater than zero."))
        doc.append("lines", {
            "payment_type": l.get("type") or "Cash",
            "collection_slip_no": l.get("slip_no"),
            "cheque": l.get("cheque"),
            "payment_entry": l.get("payment_entry"),
            "tenant": l.get("tenant"),
            "unit": l.get("unit"),
            "amount": amount,
            "remarks": l.get("remarks"),
        })
        total += amount

    doc.total_amount = total
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    return {"batch": doc.name, "lines": len(doc.lines), "total": _kk(total)}


@frappe.whitelist()
def attach_deposit_slip(batch, file_url):
    """Link an uploaded private image to the batch's optional slip field."""
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Deposit Batch", batch)
    for line in doc.lines:
        if line.unit:
            require_building_access(frappe.db.get_value("Unit", line.unit,
                                                        "building"))
        elif line.tenant:
            require_tenant_access(line.tenant)
    if doc.status != "Draft":
        frappe.throw(_("Attach the deposit slip before banking the batch."))
    if not str(file_url or "").lower().endswith((".jpg", ".jpeg", ".png")):
        frappe.throw(_("Choose a JPG or PNG image of the deposit slip."))
    if not frappe.db.get_value("File", {
            "file_url": file_url, "attached_to_doctype": "Deposit Batch",
            "attached_to_name": batch, "is_private": 1}, "name"):
        frappe.throw(_("Upload a private slip file attached to this batch."))
    doc.slip_scan = file_url
    doc.save(ignore_permissions=True)
    return {"batch": doc.name, "slip_scan": doc.slip_scan}


@frappe.whitelist()
def deposit_batch(batch, on=None, reason=None):
    """The slip went in. Historical cheques are presented; cash moves to bank."""
    guard(MD, GM, ACC)
    frappe.db.sql("SELECT name FROM `tabDeposit Batch` WHERE name = %s "
                  "FOR UPDATE", (batch,))
    doc = frappe.get_doc("Deposit Batch", batch)
    for line in doc.lines:
        if line.unit:
            require_building_access(frappe.db.get_value("Unit", line.unit,
                                                        "building"))
        elif line.tenant:
            require_tenant_access(line.tenant)
    if doc.status != "Draft":
        frappe.throw(_("{0} is {1}.").format(batch, doc.status))
    for l in doc.lines:
        if l.cheque:
            cheque = frappe.get_doc("Cheque", l.cheque)
            if cheque.direction != "Incoming" or cheque.status != "Received":
                frappe.throw(_(
                    "{0} is no longer an incoming cheque on hand."
                ).format(l.cheque))
            if (cheque.party != l.tenant or cheque.unit != l.unit
                    or flt(cheque.amount, 2) != flt(l.amount, 2)
                    or cheque.building != frappe.db.get_value("Unit", l.unit, "building")):
                frappe.throw(_("Cheque {0} changed; review the batch.").format(l.cheque))
            if cheque.deposit_batch and cheque.deposit_batch != doc.name:
                frappe.throw(_("{0} belongs to deposit batch {1}.").format(
                    l.cheque, cheque.deposit_batch))
            present_cheque(l.cheque, doc.bank_account, on or today())
            frappe.db.set_value("Cheque", l.cheque, "deposit_batch", doc.name,
                                update_modified=False)
        elif l.payment_entry:
            pe = frappe.get_doc("Payment Entry", l.payment_entry)
            if (pe.docstatus != 1 or pe.payment_type != "Receive"
                    or pe.mode_of_payment != "Cash" or pe.party != l.tenant
                    or _receipt_unit(pe) != l.unit
                    or flt(pe.paid_amount) != flt(l.amount)
                    or not _depositable_cash_account(pe.paid_to, doc.company)):
                frappe.throw(_("Cash receipt {0} changed; review the batch.")
                             .format(l.payment_entry))
            source = pe.paid_to
            target = _paid_to(doc.bank_account, doc.company)
            if source == target or not target:
                frappe.throw(_("Choose a bank account distinct from cash."))
            je = frappe.get_doc({
                "doctype": "Journal Entry", "voucher_type": "Bank Entry",
                "company": doc.company, "posting_date": on or today(),
                # ERPNext requires both Reference No and Reference Date on a
                # Bank Entry. The slip number is the external reference; a
                # batch without one still has a stable internal reference.
                "cheque_no": doc.slip_no or doc.name,
                "cheque_date": on or today(),
                "user_remark": "Deposit batch {0}: cash receipt {1}".format(
                    doc.name, pe.name),
                "accounts": [
                    {"account": target, "debit_in_account_currency": flt(l.amount)},
                    {"account": source, "credit_in_account_currency": flt(l.amount)},
                ],
            })
            je.insert(ignore_permissions=True)
            je.submit()
        else:
            frappe.throw(_("Cash line has no posted receipt. Correct the draft "
                           "batch before banking it."))

    doc.status = "Deposited"
    doc.deposited_by = frappe.session.user
    doc.save(ignore_permissions=True)
    return {"batch": doc.name, "status": doc.status}


# ------------------------------------------------------------ head lease side

@frappe.whitelist()
def pay_head_lease(head_lease, row, payload=None):
    """Legacy schedule-only action; use a posted bill and Payment Entry."""
    guard(MD, ACC)
    frappe.throw(_("Use Landlord Payments to pay an issued Head Lease bill. "
                   "A schedule status alone does not post a payment."))


# --------------------------------------------------------------------- nightly

def nightly():
    """Cheques maturing today are surfaced for presentation, and anything
    presented long ago without an outcome is flagged rather than forgotten."""
    notice = int(_settings().presentation_notice_days or 14)
    horizon = add_days(today(), notice)
    due = frappe.get_all(
        "Cheque",
        filters={"direction": "Incoming", "status": "Received",
                 "cheque_date": ["<=", horizon]},
        fields=["name", "cheque_date", "amount", "party"])
    for c in due:
        frappe.publish_realtime("darkbrown_cheque_due", {"cheque": c.name})
    frappe.db.commit()
    return len(due)


def _kk(v):
    """Keep two decimal places in receipt and other finance API amounts."""
    return round(flt(v), 2)


# ------------------------------------------------------------------- receipts

#: How many receipts the list carries before it says it is capped.
RECEIPT_CAP = 300


def _short_user(user):
    if not user or user == "Administrator":
        return "System"
    full = frappe.db.get_value("User", user, "full_name") or user
    bits = full.split()
    return bits[0] + (" " + bits[-1][0] + "." if len(bits) > 1 else "")


def _receipt_row(pe, names=None, cheque_refs=None):
    names = names or {}
    mode = (pe.mode_of_payment or "").lower()
    return {
        "id": pe.name,
        "t": pe.party,
        "tn": names.get(pe.party, pe.party),
        "party": names.get(pe.party, pe.party),
        # The screen groups by how the money actually arrived, because a cash
        # receipt needs a collection slip behind it and a cheque needs the
        # bank to have confirmed the clearing first.
        "kind": ("Cash received" if "cash" in mode
                 else "Cheque cleared" if "cheque" in mode
                 else (pe.mode_of_payment or "Transfer") + " received"),
        "amt": flt(pe.paid_amount),
        "when": str(pe.posting_date),
        "date": str(pe.posting_date),
        "mode": pe.mode_of_payment or "—",
        "ref": pe.reference_no or "—",
        "chq": (pe.reference_no if cheque_refs is not None
                and pe.reference_no in cheque_refs else ""),
        "stmt": pe.reference_no or "",
        "acct": pe.paid_to or "—",
        "un": flt(pe.unallocated_amount),
        "st": ("Cancelled" if pe.docstatus == 2 else
               "Draft" if pe.docstatus == 0 else "Issued"),
        "alloc": ("Cancelled" if pe.docstatus == 2 else
                  "Draft" if pe.docstatus == 0 else
                  "Part-allocated" if flt(pe.unallocated_amount) > 0.005
                  else "Allocated"),
        "by": _short_user(pe.owner),
    }


@frappe.whitelist()
def receipts(q=None, limit=None):
    """All receipt states, with complete scoped totals and a capped row list.

    A receipt is a Payment Entry. There is no separate receipt record and
    there should not be one — the screen had an empty array behind it and a
    detail view that said it was not wired, which is what happens when a list
    exists before the thing it lists does.
    """
    guard(MD, GM, ACC)
    limit = max(1, min(int(limit or RECEIPT_CAP), RECEIPT_CAP))
    filters = {"payment_type": "Receive", "docstatus": ["in", [0, 1, 2]]}
    allowed = allowed_buildings()
    if allowed is not None:
        tenants = set(frappe.get_all(
            "Tenancy Agreement", filters={"building": ["in", sorted(allowed)]},
            pluck="tenant"))
        if not tenants:
            return {"rows": [], "total": 0, "value": 0,
                    "unallocated": 0, "capped": False, "counts": {}}
        filters["party"] = ["in", sorted(tenants)]

    rows = []
    page_size = 500
    while True:
        page = frappe.get_all(
            "Payment Entry", filters=filters,
            fields=["name", "party", "paid_amount", "posting_date",
                    "mode_of_payment", "reference_no", "paid_to", "docstatus",
                    "unallocated_amount", "owner"],
            order_by="posting_date desc, creation desc, name desc",
            limit_start=len(rows), limit_page_length=page_size)
        rows.extend(page)
        if len(page) < page_size:
            break

    parties = {r.party for r in rows if r.party}
    names = {}
    if parties:
        names = {c.name: (c.customer_name or c.name) for c in frappe.get_all(
            "Customer", filters={"name": ["in", list(parties)]},
            fields=["name", "customer_name"])}

    refs = {r.reference_no for r in rows if r.reference_no}
    cheque_refs = set(frappe.get_all(
        "Cheque", filters={"name": ["in", list(refs)]}, pluck="name")) \
        if refs else set()
    out = [_receipt_row(r, names, cheque_refs) for r in rows]
    if q:
        needle = str(q).lower()
        out = [r for r in out if needle in " ".join(
            [r["id"], str(r["tn"]), r["ref"], r["mode"]]).lower()]
    issued = [r for r in out if r["st"] == "Issued"]
    return {
        "rows": out[:limit],
        "total": len(out),
        "value": round(sum(r["amt"] for r in issued), 2),
        "unallocated": round(sum(r["un"] for r in issued), 2),
        "receipted_cheques": [r["chq"] for r in issued if r["chq"]],
        "counts": {
            "issued": len(issued),
            "draft": sum(r["st"] == "Draft" for r in out),
            "cancelled": sum(r["st"] == "Cancelled" for r in out),
            "cash": sum(r["kind"] == "Cash received" for r in issued),
            "cheque": sum(r["kind"] == "Cheque cleared" for r in issued),
        },
        "capped": len(out) > limit,
    }


@frappe.whitelist()
def receipt(name):
    """One receipt, with what it settled.

    The allocation table is the point of this view. A tenant asking why their
    balance did not move by what they paid is answered by the reference lines,
    not by the header.
    """
    guard(MD, GM, ACC)
    if not frappe.db.exists("Payment Entry", name):
        frappe.throw(_("No receipt with that reference."))
    pe = frappe.get_doc("Payment Entry", name)
    if pe.payment_type != "Receive":
        frappe.throw(_("{0} is a payment, not a receipt.").format(name))
    require_tenant_access(pe.party)

    customer = (frappe.db.get_value("Customer", pe.party, "customer_name")
                if pe.party else None)
    named_cheque = bool(pe.reference_no and
                        frappe.db.exists("Cheque", pe.reference_no))
    row = _receipt_row(pe, {pe.party: customer or pe.party},
                       {pe.reference_no} if named_cheque else set())

    applied = []
    row["inv"] = ""
    for ref in pe.references or []:
        outstanding = frappe.db.get_value(
            ref.reference_doctype, ref.reference_name,
            "outstanding_amount") if ref.reference_name else None
        applied.append({
            "dt": ref.reference_doctype,
            "id": ref.reference_name,
            "total": flt(ref.total_amount),
            "alloc": flt(ref.allocated_amount),
            "left": flt(outstanding) if outstanding is not None else None,
        })

    cheque = None
    if pe.reference_no and frappe.db.exists("DocType", "Cheque"):
        filters = ({"name": pe.reference_no} if named_cheque
                   else {"cheque_no": pe.reference_no})
        hit = frappe.get_all(
            "Cheque", filters=filters,
            fields=["name", "status", "cheque_date", "bank"], limit=1)
        if hit:
            cheque = {"id": hit[0].name, "st": hit[0].status,
                      "d": str(hit[0].cheque_date or ""),
                      "bank": hit[0].bank or "—"}

    row["applied"] = applied
    row["inv"] = (", ".join(f"{a['id']} {a['alloc']:,.0f}" for a in applied)
                  or ("unallocated" if flt(pe.unallocated_amount)
                      else "nothing open to settle"))
    row["applied"] = applied
    row["cheque"] = cheque
    row["remarks"] = pe.remarks or ""
    return row
