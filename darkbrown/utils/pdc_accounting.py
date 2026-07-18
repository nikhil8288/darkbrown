# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt
"""
PDC Cheque accounting engine (Phase 2).

mark_cleared(pdc, clearance_date)
    Incoming Rent  -> Payment Entry (Receive) against the tenant's oldest
                      outstanding Sales Invoices (FIFO), cost centre = building.
    Outgoing Rent  -> Payment Entry (Pay) against the landlord's oldest
                      outstanding Purchase Invoices (FIFO).
    Security type  -> refuses; use bank_security_deposit() which books
                      Dr Bank / Cr Security Deposits Held (a liability -
                      NEVER income).

mark_bounced(pdc)
    Cancels a linked submitted Payment Entry, sets status Bounced
    (which fires the existing T5 Accounts handoff), records bounce_date.

Philosophy matches the rent invoicer: PE_AUTO_SUBMIT = False means every
generated entry lands as Draft for Accounts to review and submit. Flip to
True once the team trusts the engine.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

PE_AUTO_SUBMIT = False          # drafts first; flip after trust is earned
SECURITY_LIABILITY_NAME = "Security Deposits Held"


# ------------------------------------------------------------ helpers

def _company():
	return frappe.db.get_value("Company", {}, ["name", "abbr",
		"default_receivable_account", "default_payable_account"], as_dict=True)


def _bank_account(company):
	acc = frappe.db.get_value(
		"Account",
		{"account_type": "Bank", "company": company, "is_group": 0},
		"name",
	)
	if not acc:
		frappe.throw(_("No Bank account found in the Chart of Accounts."))
	return acc


def _cost_center(building):
	"""Same convention as rent_invoicing: Cost Center named after the building."""
	if building:
		cc = frappe.db.get_value(
			"Cost Center", {"cost_center_name": building, "is_group": 0}, "name"
		)
		if cc:
			return cc
	return frappe.db.get_value("Company", {}, "cost_center")


def _building_for(pdc):
	if pdc.get("tenant_rental_agreement"):
		return frappe.db.get_value(
			"Tenant Rental Agreement", pdc.tenant_rental_agreement, "building")
	if pdc.get("landlord_contract"):
		return frappe.db.get_value(
			"Landlord Contract", pdc.landlord_contract, "building")
	return None


def _party_for(pdc, incoming):
	"""Resolve the Customer/Supplier docname. The party field on PDC may hold
	either the docname or a display name; try both."""
	doctype = "Customer" if incoming else "Supplier"
	name_field = "customer_name" if incoming else "supplier_name"
	raw = pdc.get("party")
	# via agreement first (most reliable)
	if incoming and pdc.get("tenant_rental_agreement"):
		t = frappe.db.get_value(
			"Tenant Rental Agreement", pdc.tenant_rental_agreement, "tenant")
		if t:
			return t
	if not incoming and pdc.get("landlord_contract"):
		l = frappe.db.get_value(
			"Landlord Contract", pdc.landlord_contract, "landlord")
		if l:
			return l
	if raw:
		if frappe.db.exists(doctype, raw):
			return raw
		hit = frappe.db.get_value(doctype, {name_field: raw}, "name")
		if hit:
			return hit
	return None


def _fifo_invoices(incoming, party, amount):
	"""Oldest outstanding invoices for the party, allocated FIFO up to amount.
	Returns (references list, unallocated remainder)."""
	inv_doctype = "Sales Invoice" if incoming else "Purchase Invoice"
	party_field = "customer" if incoming else "supplier"
	rows = frappe.get_all(
		inv_doctype,
		filters={party_field: party, "docstatus": 1,
		         "outstanding_amount": [">", 0.005]},
		fields=["name", "outstanding_amount", "due_date", "posting_date",
		        "grand_total"],
		order_by="due_date asc, posting_date asc",
	)
	refs, remaining = [], flt(amount)
	for r in rows:
		if remaining <= 0.005:
			break
		alloc = min(remaining, flt(r.outstanding_amount))
		refs.append({
			"reference_doctype": inv_doctype,
			"reference_name": r.name,
			"total_amount": flt(r.grand_total),
			"outstanding_amount": flt(r.outstanding_amount),
			"allocated_amount": alloc,
		})
		remaining -= alloc
	return refs, remaining


# ------------------------------------------------------------ actions

@frappe.whitelist()
def mark_cleared(pdc, clearance_date=None, submit=None):
	"""Bank confirmed the cheque. Creates the Payment Entry (draft by
	default) and moves the PDC to Cleared."""
	doc = frappe.get_doc("PDC Cheque", pdc)
	if not doc.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if doc.status == "Cleared":
		frappe.throw(_("Already cleared."))
	if (doc.get("cheque_type") or "Rent") == "Security Deposit":
		frappe.throw(_(
			"This is a SECURITY cheque - it must not create income. "
			"If it was actually banked, use bank_security_deposit() "
			"(books Dr Bank / Cr {0}).").format(SECURITY_LIABILITY_NAME))

	incoming = "Incoming" in (doc.direction or "")
	clearance_date = clearance_date or nowdate()
	co = _company()
	party = _party_for(doc, incoming)
	if not party:
		frappe.throw(_(
			"Cannot resolve the {0} for this cheque - set the party or "
			"agreement link first.").format("Customer" if incoming else "Supplier"))

	refs, remainder = _fifo_invoices(incoming, party, doc.amount)
	building = _building_for(doc)
	bank = _bank_account(co.name)

	pe = frappe.new_doc("Payment Entry")
	pe.payment_type = "Receive" if incoming else "Pay"
	pe.company = co.name
	pe.posting_date = clearance_date
	pe.party_type = "Customer" if incoming else "Supplier"
	pe.party = party
	pe.paid_amount = flt(doc.amount)
	pe.received_amount = flt(doc.amount)
	if incoming:
		pe.paid_from = co.default_receivable_account
		pe.paid_to = bank
	else:
		pe.paid_from = bank
		pe.paid_to = co.default_payable_account
	pe.reference_no = doc.cheque_number
	pe.reference_date = doc.cheque_date or clearance_date
	pe.cost_center = _cost_center(building)
	pe.remarks = (f"Cheque {doc.cheque_number} ({doc.bank_name or ''}) "
	              f"cleared {clearance_date}. PDC {doc.name}.")
	for r in refs:
		pe.append("references", r)
	pe.flags.ignore_permissions = True
	pe.insert()

	do_submit = PE_AUTO_SUBMIT if submit is None else bool(int(submit))
	if do_submit:
		pe.submit()

	doc.db_set("status", "Cleared")
	doc.db_set("cleared_date", clearance_date)
	if doc.meta.has_field("payment_entry"):
		doc.db_set("payment_entry", pe.name)
	frappe.db.commit()

	alloc_msg = (f"allocated to {len(refs)} invoice(s)"
	             + (f", {remainder:,.2f} QAR unallocated (advance)" if remainder > 0.005 else ""))
	return {
		"payment_entry": pe.name,
		"submitted": do_submit,
		"msg": (f"Payment Entry {pe.name} created as "
		        f"{'submitted' if do_submit else 'DRAFT (Accounts to review and submit)'}; "
		        f"{alloc_msg}."),
	}


@frappe.whitelist()
def bank_security_deposit(pdc, deposit_date=None):
	"""A security cheque was actually banked: Dr Bank / Cr Security Deposits
	Held. Income is never touched."""
	doc = frappe.get_doc("PDC Cheque", pdc)
	if not doc.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if (doc.get("cheque_type") or "") != "Security Deposit":
		frappe.throw(_("This action is only for Security Deposit cheques."))

	co = _company()
	liability = frappe.db.get_value(
		"Account",
		{"account_name": SECURITY_LIABILITY_NAME, "company": co.name, "is_group": 0},
		"name",
	)
	if not liability:
		frappe.throw(_("Account '{0}' not found in the Chart of Accounts.")
		             .format(SECURITY_LIABILITY_NAME))
	deposit_date = deposit_date or nowdate()
	bank = _bank_account(co.name)

	je = frappe.new_doc("Journal Entry")
	je.company = co.name
	je.posting_date = deposit_date
	je.user_remark = (f"Security cheque {doc.cheque_number} banked. "
	                  f"PDC {doc.name}. Held as refundable liability.")
	je.append("accounts", {"account": bank, "debit_in_account_currency": flt(doc.amount)})
	je.append("accounts", {"account": liability, "credit_in_account_currency": flt(doc.amount)})
	je.flags.ignore_permissions = True
	je.insert()
	if PE_AUTO_SUBMIT:
		je.submit()

	doc.db_set("status", "Cleared")
	doc.db_set("cleared_date", deposit_date)
	if doc.meta.has_field("journal_entry"):
		doc.db_set("journal_entry", je.name)
	frappe.db.commit()
	return {"journal_entry": je.name,
	        "msg": f"Journal Entry {je.name} created "
	               f"({'submitted' if PE_AUTO_SUBMIT else 'DRAFT'}): "
	               f"Dr Bank / Cr {SECURITY_LIABILITY_NAME}."}


@frappe.whitelist()
def mark_bounced(pdc, bounce_date=None):
	"""Bank returned the cheque. Cancels the linked Payment Entry (if
	submitted), deletes it (if draft), sets Bounced - which fires the
	existing T5 recovery handoff to Accounts."""
	doc = frappe.get_doc("PDC Cheque", pdc)
	if not doc.has_permission("write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	msg_parts = []
	pe_name = doc.get("payment_entry")
	if pe_name and frappe.db.exists("Payment Entry", pe_name):
		pe = frappe.get_doc("Payment Entry", pe_name)
		if pe.docstatus == 1:
			pe.cancel()
			msg_parts.append(f"Payment Entry {pe.name} cancelled")
		elif pe.docstatus == 0:
			pe.delete()
			msg_parts.append(f"Draft Payment Entry {pe_name} deleted")
		if doc.meta.has_field("payment_entry"):
			doc.db_set("payment_entry", None)

	if doc.meta.has_field("bounce_date"):
		doc.db_set("bounce_date", bounce_date or nowdate())
	# .save() (not db_set) so t5_assign_bounced's has_value_changed fires
	doc.status = "Bounced"
	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()
	msg_parts.append("status set to Bounced - Accounts recovery task raised")
	return {"msg": "; ".join(msg_parts)}
