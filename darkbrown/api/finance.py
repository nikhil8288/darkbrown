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
    data = frappe.parse_json(payload)
    count = int(data.get("count") or 1)
    if count < 1:
        frappe.throw(_("A cheque batch needs at least one cheque."))

    first_no = str(data.get("cheque_no") or "").strip()
    if not first_no:
        frappe.throw(_("A cheque needs its number."))

    amount = flt(data.get("amount"))
    if not amount and ta:
        amount = flt(ta.monthly_rent)
    if amount <= 0:
        frappe.throw(_("A cheque amount must be greater than zero."))

    direction = data.get("direction") or "Incoming"
    if direction not in ("Incoming", "Outgoing"):
        frappe.throw(_("Cheque direction must be Incoming or Outgoing."))
    agreement = data.get("tenancy_agreement")
    ta = frappe.get_doc("Tenancy Agreement", agreement) if agreement else None
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

    doc.status = "Cleared"
    doc.cleared_on = on or today()
    if doc.party and not doc.payment_entry:
        if doc.direction == "Incoming":
            doc.payment_entry = _receipt(doc.party, flt(doc.amount),
                                         doc.cleared_on, doc.bank_account,
                                         reference=doc.name)[0]
        else:
            doc.payment_entry = _supplier_payment(
                doc.party, flt(doc.amount), doc.cleared_on, doc.bank_account,
                reference=doc.name, head_lease=doc.head_lease)[0]
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
    items = [{
        "item_code": item,
        "item_name": f"Rent — {line.unit}",
        "description": (f"Rent for {line.unit}, "
                        f"{run.period_start} to {run.period_end}"),
        "qty": 1,
        "rate": flt(line.agreement_amount),
        "cost_center": _cost_center(run.building),
    }]
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
         "docstatus": ["<", 2]}, ["name", "grand_total"], as_dict=True)
    if existing:
        return {"invoice": existing.name, "created": False,
                "status": "Draft", "amount": _kk(existing.grand_total),
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
    if pi.docstatus == 1:
        return {"invoice": pi.name, "status": "Submitted"}
    if pi.docstatus != 0:
        frappe.throw(_("{0} is cancelled and cannot be issued.").format(invoice))
    pi.flags.ignore_permissions = True
    pi.submit()
    return {"invoice": pi.name, "status": "Submitted"}


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

    pe, applied, on_account = _receipt(
        tenant, amount, data.get("on") or today(),
        data.get("bank_account"), mode=data.get("mode"),
        reference=data.get("reference"), invoice=data.get("invoice"))
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
        if account:
            return account

    mapped = frappe.db.get_value("Mode of Payment Account", {
        "parent": "Cash", "company": company,
    }, "default_account")
    if not mapped:
        return None
    details = frappe.db.get_value(
        "Account", mapped,
        ["root_type", "account_type", "is_group", "disabled", "account_name"],
        as_dict=True)
    if (details and details.root_type == "Asset"
            and details.account_type == "Cash" and not details.is_group
            and not details.disabled
            and details.account_name != "Historical Cutover Control"):
        return mapped
    return None


def _receipt(customer, amount, on, bank_account=None, mode=None,
             reference=None, invoice=None):
    """Post a receipt and say where the money went.

    Oldest-first remains the rule, because that is what the ageing report
    assumes and what a tenant disputing a balance is shown. A named invoice is
    the one exception, and it is a deliberate one: a tenant who pays a
    specific invoice and is credited against an older one will dispute it. The
    named invoice is settled first and anything left over then falls to the
    oldest, so the exception never becomes a way to leave old debt hidden.
    """
    company = _company()
    account = _paid_to(bank_account or _settings().default_bank_account,
                       company)
    if not account:
        frappe.throw(_(
            "No bank or cash ledger is configured. Set the Default Bank "
            "Account in DBR Settings or pass a valid Bank Account."))

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
    account = _paid_to(bank_account or _settings().default_bank_account,
                       company)
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

@frappe.whitelist()
def create_deposit_batch(payload):
    """Cash and cheques going to the bank as one slip.

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
    bank_account = (data.get("bank_account")
                    or _settings().default_bank_account)
    if not bank_account or not frappe.db.exists("Bank Account", bank_account):
        frappe.throw(_("Choose a valid company Bank Account for the deposit."))

    # Treat every browser value as untrusted.  In particular, a caller must
    # not be able to deposit one of our outgoing cheques, reuse a cheque in
    # two open slips, or change its amount/tenant while building the batch.
    seen_cheques = set()
    checked_lines = []
    for line in lines:
        payment_type = line.get("type") or "Cash"
        if payment_type not in ("Cash", "Cheque"):
            frappe.throw(_("Deposit line type must be Cash or Cheque."))

        checked = dict(line)
        if payment_type == "Cheque":
            cheque_name = line.get("cheque")
            if not cheque_name:
                frappe.throw(_("Every cheque line needs a cheque."))
            if cheque_name in seen_cheques:
                frappe.throw(_("{0} appears more than once in this batch.").format(
                    cheque_name))
            seen_cheques.add(cheque_name)

            cheque = frappe.get_doc("Cheque", cheque_name)
            require_record_access(cheque, "write")
            if cheque.direction != "Incoming" or cheque.status != "Received":
                frappe.throw(_(
                    "{0} must be an incoming cheque on hand before it can be "
                    "added to a deposit batch."
                ).format(cheque_name))
            if flt(line.get("amount")) != flt(cheque.amount):
                frappe.throw(_("{0} amount must match the cheque register.").format(
                    cheque_name))

            other_line = frappe.db.get_value(
                "Deposit Batch Line", {"cheque": cheque_name}, "parent")
            if other_line:
                other_status = frappe.db.get_value(
                    "Deposit Batch", other_line, "status")
                if other_status in ("Draft", "Deposited", "Reconciled"):
                    frappe.throw(_("{0} is already in deposit batch {1}.").format(
                        cheque_name, other_line))

            # Copy identity from the controlled cheque record, not the request.
            checked["tenant"] = cheque.party
            checked["unit"] = cheque.unit
            checked["amount"] = flt(cheque.amount)

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
        "slip_scan": data.get("slip_scan"),
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
def deposit_batch(batch, on=None, reason=None):
    """The slip went in. Cheques in it are presented, cash becomes a receipt.

    `reason` is the dual-control override. The controller refuses a batch
    prepared and banked by the same person unless one is given, and on a
    finance team this size that is the ordinary case rather than the
    exception — so there has to be a way to say why, and it has to be
    recorded on the batch.
    """
    guard(MD, GM, ACC)
    doc = frappe.get_doc("Deposit Batch", batch)
    for line in doc.lines:
        if line.unit:
            require_building_access(frappe.db.get_value("Unit", line.unit,
                                                        "building"))
        elif line.tenant:
            require_tenant_access(line.tenant)
    if doc.status != "Draft":
        frappe.throw(_("{0} is {1}.").format(batch, doc.status))
    if doc.prepared_by == frappe.session.user and not (reason or "").strip():
        frappe.throw(_(
            "A same-user deposit needs an override reason for the audit trail."
        ))
    if reason:
        doc.override_reason = reason.strip()

    for l in doc.lines:
        if l.cheque:
            cheque = frappe.get_doc("Cheque", l.cheque)
            if cheque.direction != "Incoming" or cheque.status != "Received":
                frappe.throw(_(
                    "{0} is no longer an incoming cheque on hand."
                ).format(l.cheque))
            if cheque.deposit_batch and cheque.deposit_batch != doc.name:
                frappe.throw(_("{0} belongs to deposit batch {1}.").format(
                    l.cheque, cheque.deposit_batch))
            present_cheque(l.cheque, doc.bank_account, on or today())
            frappe.db.set_value("Cheque", l.cheque, "deposit_batch", doc.name,
                                update_modified=False)
        elif l.tenant:
            _receipt(l.tenant, flt(l.amount), on or today(), doc.bank_account,
                     mode="Cash", reference=doc.slip_no or doc.name)

    doc.status = "Deposited"
    doc.deposited_by = frappe.session.user
    doc.save(ignore_permissions=True)
    return {"batch": doc.name, "status": doc.status}


# ------------------------------------------------------------ head lease side

@frappe.whitelist()
def pay_head_lease(head_lease, row, payload=None):
    """Rent out to the landlord. The other half of the spread."""
    guard(MD, ACC)
    data = frappe.parse_json(payload) if payload else {}
    hl = frappe.get_doc("Head Lease", head_lease)
    require_record_access(hl, "write")
    line = None
    for p in hl.payments:
        if p.name == row:
            line = p
            break
    if not line:
        frappe.throw(_("That payment is not on {0}.").format(head_lease))
    if line.status == "Cleared":
        frappe.throw(_("That payment is already settled."))

    # Cleared, not Paid. The cheque lifecycle already owns this vocabulary and
    # a second word for the same state drifts apart from the first.
    line.status = "Cleared"
    line.paid_on = data.get("on") or today()
    line.payment_mode = data.get("mode") or line.payment_mode
    if data.get("cheque"):
        line.cheque = data["cheque"]
    hl.save(ignore_permissions=True)
    return {"head_lease": hl.name, "paid": _kk(flt(line.amount))}


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
    """Money crosses to the shell in whole riyals. No scaling anywhere."""
    return round(flt(v))


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
        "st": "Cancelled" if pe.docstatus == 2 else "Issued",
        "alloc": ("Cancelled" if pe.docstatus == 2
                  else "Part-allocated" if flt(pe.unallocated_amount) > 0.005
                  else "Allocated"),
        "by": _short_user(pe.owner),
    }


@frappe.whitelist()
def receipts(q=None, limit=None):
    """Every receipt posted, newest first.

    A receipt is a Payment Entry. There is no separate receipt record and
    there should not be one — the screen had an empty array behind it and a
    detail view that said it was not wired, which is what happens when a list
    exists before the thing it lists does.
    """
    guard(MD, GM, ACC)
    limit = int(limit or RECEIPT_CAP)
    rows = frappe.get_all(
        "Payment Entry",
        filters={"payment_type": "Receive", "docstatus": ["<", 2]},
        fields=["name", "party", "paid_amount", "posting_date",
                "mode_of_payment", "reference_no", "paid_to", "docstatus",
                "unallocated_amount", "owner"],
        order_by="posting_date desc, creation desc", limit=limit)
    allowed = allowed_buildings()
    if allowed is not None:
        tenants = set(frappe.get_all(
            "Tenancy Agreement", filters={"building": ["in", sorted(allowed)]},
            pluck="tenant"))
        rows = [row for row in rows if row.party in tenants]
    if not rows:
        return {"rows": [], "total": 0, "value": 0, "unallocated": 0,
                "capped": False}

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
    return {
        "rows": out,
        "total": len(out),
        "value": round(sum(r["amt"] for r in out), 2),
        "unallocated": round(sum(r["un"] for r in out), 2),
        "capped": len(rows) >= limit,
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
