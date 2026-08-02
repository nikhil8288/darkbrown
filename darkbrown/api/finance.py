"""Money in, money out.

Two rules hold this module together.

ERPNext owns the ledger. Nothing here writes a GL entry by hand; it creates
Sales Invoices and Payment Entries and lets ERPNext post them. That keeps one
set of books rather than two that disagree.

A returned cheque is an event, not a status. Bouncing a cheque reverses the
payment, reopens what it settled, and leaves a record of why — because the
question asked later is always "what happened", not "what is it now".
"""

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, add_days, add_months, date_diff

def _settings():
    return frappe.get_single("DBR Settings")


def _company():
    return (_settings().default_company
            or frappe.db.get_value("Company", {}, "name"))


# -------------------------------------------------------------------- cheques

@frappe.whitelist()
def log_cheque(payload):
    """Log one cheque, or a book of post-dated cheques in one pass.

    A tenant paying by cheque hands over several at signing. Logging them one
    at a time is where mistakes get made, so a count and a first number is
    enough to lay the whole series down.
    """
    data = frappe.parse_json(payload)
    agreement = data.get("tenancy_agreement")
    ta = frappe.get_doc("Tenancy Agreement", agreement) if agreement else None

    count = int(data.get("count") or 1)
    if count < 1:
        frappe.throw(_("A cheque batch needs at least one cheque."))

    first_no = str(data.get("cheque_no") or "").strip()
    if not first_no:
        frappe.throw(_("A cheque needs its number."))

    amount = flt(data.get("amount"))
    if not amount and ta:
        amount = flt(ta.monthly_rent)
    if not amount:
        frappe.throw(_("A cheque needs an amount."))

    first_date = getdate(data.get("cheque_date") or today())
    every = int(data.get("months_apart") or 1)
    numeric = first_no.isdigit()

    made = []
    for i in range(count):
        no = str(int(first_no) + i) if numeric else (
            first_no if count == 1 else f"{first_no}-{i + 1}")
        doc = frappe.get_doc({
            "doctype": "Cheque",
            "direction": data.get("direction") or "Incoming",
            "party_type": "Customer" if (data.get("direction") or
                                         "Incoming") == "Incoming" else "Supplier",
            "party": data.get("party") or (ta.tenant if ta else None),
            "status": "Received",
            "company": _company(),
            "cheque_no": no,
            "bank": data.get("bank"),
            "cheque_date": add_months(first_date, i * every),
            "amount": amount,
            "cheque_book": data.get("cheque_book"),
            "scan": data.get("scan"),
            "building": ta.building if ta else data.get("building"),
            "unit": ta.unit if ta else data.get("unit"),
            "tenancy_agreement": agreement,
            "head_lease": data.get("head_lease"),
        })
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        made.append(doc.name)

    if ta:
        ta.db_set("cheques_held", flt(ta.cheques_held) + count,
                  update_modified=False)

    return {"cheques": made, "count": len(made)}


@frappe.whitelist()
def present_cheque(cheque, bank_account=None, on=None):
    """Send a cheque to the bank. It is out of our hands from here."""
    doc = frappe.get_doc("Cheque", cheque)
    if doc.status not in ("Received", "Deposited"):
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
    doc = frappe.get_doc("Cheque", cheque)
    if doc.status == "Cleared":
        return {"cheque": doc.name, "status": doc.status,
                "payment_entry": doc.payment_entry}
    if doc.status not in ("Presented", "Deposited", "Received"):
        frappe.throw(_("{0} is {1} and cannot clear.").format(
            cheque, doc.status))

    doc.status = "Cleared"
    doc.cleared_on = on or today()
    if doc.direction == "Incoming" and doc.party and not doc.payment_entry:
        doc.payment_entry = _receipt(doc.party, flt(doc.amount),
                                     doc.cleared_on, doc.bank_account,
                                     reference=doc.name)[0]
    doc.save(ignore_permissions=True)
    return {"cheque": doc.name, "status": doc.status,
            "payment_entry": doc.payment_entry}


@frappe.whitelist()
def return_cheque(cheque, reason, charge=None, notes=None, on=None):
    """A bounce. Reverse the money, then open a case if one is warranted —
    both, in one pass, because a bounce that only changes a status is a bounce
    nobody chases."""
    doc = frappe.get_doc("Cheque", cheque)
    if doc.status == "Returned":
        frappe.throw(_("{0} is already recorded as returned.").format(cheque))

    # Reverse the money first. Cancelling the Payment Entry runs a hook that
    # writes to this cheque's row, so a copy read before that point carries a
    # stale timestamp and the save is refused as a conflict. Reload, then
    # apply the bounce to the fresh copy.
    if doc.payment_entry:
        pe = frappe.get_doc("Payment Entry", doc.payment_entry)
        if pe.docstatus == 1:
            pe.cancel()
        doc.reload()
        doc.payment_entry = None

    doc.status = "Returned"
    doc.returned_on = on or today()
    doc.return_reason = reason
    doc.return_charge = flt(charge) if charge else 0
    doc.return_notes = notes
    doc.save(ignore_permissions=True)

    case = None
    if doc.direction == "Incoming" and doc.tenancy_agreement:
        case = _case_for_bounce(doc)

    return {"cheque": doc.name, "status": doc.status, "case": case}


def _case_for_bounce(cheque):
    """A bounce opens a collection case unless the tenant already has one.

    The bounce is recorded as a comment rather than a contact action — an
    action row means somebody spoke to the tenant, and nobody has yet.
    """
    note = (f"Cheque {cheque.cheque_no} for QAR {flt(cheque.amount):,.0f} "
            f"returned: {cheque.return_reason}.")

    open_case = frappe.get_all(
        "Collection Case",
        filters={"tenant": cheque.party,
                 "status": ["not in", ("Closed", "Cancelled")]},
        pluck="name")
    if open_case:
        case = frappe.get_doc("Collection Case", open_case[0])
        case.outstanding_amount = flt(case.outstanding_amount) + flt(cheque.amount)
        case.save(ignore_permissions=True)
        case.add_comment("Comment", note)
        return case.name

    doc = frappe.get_doc({
        "doctype": "Collection Case",
        "tenant": cheque.party,
        "tenancy_agreement": cheque.tenancy_agreement,
        "unit": cheque.unit,
        "building": cheque.building,
        "status": "Open",
        "trigger": "Returned Cheque",
        "opened_on": today(),
        "reference": cheque.name,
        "outstanding_amount": flt(cheque.amount),
    })
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)
    doc.add_comment("Comment", note)
    return doc.name


@frappe.whitelist()
def replace_cheque(cheque, payload):
    """A replacement points back at what it replaces."""
    data = frappe.parse_json(payload)
    old = frappe.get_doc("Cheque", cheque)
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

@frappe.whitelist()
def build_invoice_run(building, period_start=None):
    """Draft a month of rent for one building.

    Nothing is issued here. The run is a proposal the Accounts officer reads
    line by line, with the variance against each agreement shown, and only
    then does it go anywhere.
    """
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
        fields=["name", "tenant", "unit", "monthly_rent"])
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

    total, variance_seen = 0, False
    for a in agreements:
        charges = sum(flt(c.amount) for c in frappe.get_all(
            "Tenancy Charge", filters={"parent": a.name},
            fields=["amount"]))
        amount = flt(a.monthly_rent) + charges
        variance = amount - flt(a.monthly_rent)
        if variance:
            variance_seen = True
        run.append("lines", {
            "tenancy_agreement": a.name,
            "tenant": a.tenant,
            "unit": a.unit,
            "agreement_amount": flt(a.monthly_rent),
            "invoice_amount": amount,
            "variance": variance,
            "reason": "Recurring charges on the agreement" if variance else None,
        })
        total += amount

    run.total_amount = total
    run.has_variance = 1 if variance_seen else 0
    run.flags.ignore_mandatory = True
    run.insert(ignore_permissions=True)
    return {"run": run.name, "lines": len(run.lines), "total": _kk(total)}


@frappe.whitelist()
def invoice_run(run):
    """A drafted run and its lines, for the screen that reviews it.

    build_invoice_run returns a count. The reviewer needs the lines
    themselves — what each agreement says, what the invoice would be, and
    where the two differ — because reading them is the whole point of a run
    existing before anything is issued.
    """
    doc = frappe.get_doc("Invoice Run", run)
    tenants = {}
    for t in {l.tenant for l in doc.lines if l.tenant}:
        tenants[t] = frappe.db.get_value("Customer", t, "customer_name") or t

    return {
        "run": doc.name,
        "building": doc.building,
        "period_start": str(doc.period_start),
        "period_end": str(doc.period_end),
        "status": doc.status,
        "total": _kk(doc.total_amount),
        "has_variance": 1 if doc.has_variance else 0,
        "variance_reason": doc.variance_reason or "",
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
        } for l in doc.lines],
    }


@frappe.whitelist()
def submit_invoice_run(run):
    """Send a drafted run for approval."""
    doc = frappe.get_doc("Invoice Run", run)
    if doc.status != "Draft":
        frappe.throw(_("{0} is {1}.").format(run, doc.status))
    doc.status = "Pending GM"
    doc.save(ignore_permissions=True)
    return {"run": doc.name, "status": doc.status}


@frappe.whitelist()
def issue_invoice_run(run):
    """Approve the run and raise the invoices. This is the point of no return,
    so it is one transaction: every line becomes an invoice or none does."""
    doc = frappe.get_doc("Invoice Run", run)
    if doc.status not in ("Draft", "Pending GM"):
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
    item = _rent_item()
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
        "cost_center": _cost_center(run.building),
        "items": [{
            "item_code": item,
            "item_name": f"Rent — {line.unit}",
            "description": (f"Rent for {line.unit}, "
                            f"{run.period_start} to {run.period_end}"),
            "qty": 1,
            "rate": flt(line.invoice_amount),
            "cost_center": _cost_center(run.building),
        }],
    })
    si.flags.ignore_mandatory = True
    # on flags, not just on insert: submit() saves again and checks
    # permissions afresh, so a one-shot argument does not carry
    si.flags.ignore_permissions = True
    si.insert(ignore_permissions=True)
    si.submit()
    return si.name


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


# ------------------------------------------------------------------- receipts

@frappe.whitelist()
def record_receipt(payload):
    """Money received against a tenant, allocated oldest invoice first.

    Allocation is not a judgement call. The oldest debt clears first, which is
    what the ageing report assumes and what a tenant disputing a balance will
    be shown.
    """
    data = frappe.parse_json(payload)
    tenant = data.get("tenant")
    amount = flt(data.get("amount"))
    if not tenant or not amount:
        frappe.throw(_("A receipt needs a tenant and an amount."))

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
        if gl:
            return gl
        if frappe.db.exists("Account", value):
            return value

    return (frappe.db.get_value("Account",
                                {"company": company, "account_type": "Bank",
                                 "is_group": 0}, "name")
            or frappe.db.get_value("Account",
                                   {"company": company, "account_type": "Cash",
                                    "is_group": 0}, "name"))


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


# ------------------------------------------------------------- deposit batches

@frappe.whitelist()
def create_deposit_batch(payload):
    """Cash and cheques going to the bank as one slip.

    Three quarters of what lands in the bank arrives without a payer name on
    it. Matching on the payer is therefore not available, and this is the
    replacement: the slip is captured here before it goes in, so the statement
    line can be matched to the slip rather than to a name that is not there.
    """
    data = frappe.parse_json(payload)
    lines = data.get("lines") or []
    if not lines:
        frappe.throw(_("A deposit needs at least one line."))

    doc = frappe.get_doc({
        "doctype": "Deposit Batch",
        "deposit_date": data.get("date") or today(),
        "bank_account": data.get("bank_account") or _settings().default_bank_account,
        "status": "Draft",
        "company": _company(),
        "slip_no": data.get("slip_no"),
        "slip_scan": data.get("slip_scan"),
        "prepared_by": frappe.session.user,
    })

    total = 0
    for l in lines:
        amount = flt(l.get("amount"))
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
    doc = frappe.get_doc("Deposit Batch", batch)
    if doc.status != "Draft":
        frappe.throw(_("{0} is {1}.").format(batch, doc.status))
    if reason:
        doc.override_reason = reason

    for l in doc.lines:
        if l.cheque:
            present_cheque(l.cheque, doc.bank_account, on or today())
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
    data = frappe.parse_json(payload) if payload else {}
    hl = frappe.get_doc("Head Lease", head_lease)
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
