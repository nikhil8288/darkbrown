# -*- coding: utf-8 -*-
# =============================================================================
#  DARKBROWN — DOC INTAKE PHASE 2 (single consolidated module)
#  App: darkbrown | Site: erp.darkbrown.qa | ERPNext v15
#
#  Path in repo:  darkbrown/darkbrown/api/doc_intake_phase2.py
#
#  Contains all three Phase 2 features:
#    PART A — Patch: creates "Party Document" child DocType (custom) and
#             attaches it as a child table to Customer (Tenant) and
#             Supplier (Landlord).
#             patches.txt (under [post_model_sync]):
#                 darkbrown.api.doc_intake_phase2.execute
#    PART B — Missing-date guard: blocks a Cheque Batch Document Register
#             from moving to "Pushed" while any CONFIRMED cheque row has no
#             cheque date. Wire via hooks.py doc_events (see bottom docstring).
#    PART C — mark_cleared_v2: clears a PDC Cheque, backfills a missing
#             cheque date, and creates + submits a Payment Entry reconciled
#             FIFO against the party's outstanding invoices.
#
#  >>> FIELDNAME CONFIG BLOCK BELOW — verify against your actual DocTypes
#      before first deploy. Everything guessable is centralised there. <<<
# =============================================================================

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate
from darkbrown.guards import guard, ACC, DOC, MD

# -----------------------------------------------------------------------------
# CONFIG — adjust fieldnames here if they differ on your site
# -----------------------------------------------------------------------------

COMPANY = "DarkBrown RealEstate"
CURRENCY = "QAR"

# Document Register
REGISTER_DOCTYPE = "Document Register"
REGISTER_STATUS_FIELD = "status"                 # e.g. Draft / In Review / Confirmed / Pushed
REGISTER_DOCTYPE_FIELD = "document_type"         # Select: Cheque Batch, QID/National ID, ...
REGISTER_CHEQUES_TABLE = "cheques"               # child table fieldname on Document Register
REGISTER_SOURCE_FILE_FIELD = "source_document"   # Attach field with the scanned PDF

# Cheque child row (inside Document Register)
ROW_CONFIRMED_FIELD = "confirmed"
ROW_CHEQUE_NO_FIELD = "cheque_no"
ROW_CHEQUE_DATE_FIELD = "cheque_date"

# Party links on Document Register (whichever applies per document type)
REGISTER_CUSTOMER_FIELD = "customer"             # Link -> Customer (tenant docs)
REGISTER_SUPPLIER_FIELD = "supplier"             # Link -> Supplier (landlord docs)

# Optional extraction fields on Document Register used to fill Party Document
REGISTER_DOC_NO_FIELD = "id_number"              # QID no / passport no if present
REGISTER_EXPIRY_FIELD = "expiry_date"
REGISTER_ISSUE_FIELD = "issue_date"

# Document types that should attach to a party's document list when pushed
PARTY_ATTACHABLE_TYPES = (
    "QID/National ID",
    "Passport",
    "Tenant Contract",
    "Landlord Contract",
    "Owner Contract",
    "Utility/Other",
)

# PDC Cheque
PDC_DOCTYPE = "PDC Cheque"
PDC_STATUS_FIELD = "status"                      # In Hand / Deposited / Cleared / Bounced ...
PDC_DIRECTION_FIELD = "direction"                # "Incoming (from Tenant)" / "Outgoing (to Landlord)"
PDC_CHEQUE_NO_FIELD = "cheque_number"
PDC_CHEQUE_DATE_FIELD = "cheque_date"
PDC_CLEARED_DATE_FIELD = "cleared_date"
PDC_AMOUNT_FIELD = "amount"
PDC_BANK_FIELD = "bank_name"
PDC_TRA_FIELD = "tenant_rental_agreement"        # Link -> Tenant Rental Agreement
PDC_LLC_FIELD = "landlord_contract"              # Link -> Landlord Contract
PDC_PAYMENT_ENTRY_FIELD = "payment_entry"        # optional Link -> Payment Entry (skipped if absent)

DIRECTION_INCOMING = "Incoming (from Tenant)"

# Party fields on the agreement doctypes
TRA_CUSTOMER_FIELD = "customer"                  # Tenant Rental Agreement -> Customer
LLC_SUPPLIER_FIELD = "supplier"                  # Landlord Contract -> Supplier

# Child DocType created by the patch
PARTY_DOC_DOCTYPE = "Party Document"
PARTY_TABLE_FIELDNAME = "custom_party_documents"


# =============================================================================
# PART A — PATCH: Party Document child DocType + child tables on parties
#   patches.txt: darkbrown.api.doc_intake_phase2.execute   (post_model_sync)
#   Idempotent: safe to re-run.
# =============================================================================

def execute():
    _create_party_document_doctype()
    _add_party_table_field("Customer")
    _add_party_table_field("Supplier")
    frappe.db.commit()


def _create_party_document_doctype():
    if frappe.db.exists("DocType", PARTY_DOC_DOCTYPE):
        return

    doc = frappe.get_doc({
        "doctype": "DocType",
        "name": PARTY_DOC_DOCTYPE,
        "module": "Darkbrown",          # adjust if your module label differs
        "custom": 1,
        "istable": 1,
        "editable_grid": 1,
        "fields": [
            {
                "fieldname": "document_type",
                "label": "Document Type",
                "fieldtype": "Select",
                "options": "QID/National ID\nPassport\nTenant Contract\nLandlord Contract\nOwner Contract\nCheque Batch\nUtility/Other",
                "in_list_view": 1,
                "reqd": 1,
            },
            {
                "fieldname": "document_no",
                "label": "Document No",
                "fieldtype": "Data",
                "in_list_view": 1,
            },
            {
                "fieldname": "issue_date",
                "label": "Issue Date",
                "fieldtype": "Date",
            },
            {
                "fieldname": "expiry_date",
                "label": "Expiry Date",
                "fieldtype": "Date",
                "in_list_view": 1,
            },
            {
                "fieldname": "file",
                "label": "File",
                "fieldtype": "Attach",
                "in_list_view": 1,
            },
            {
                "fieldname": "source_register",
                "label": "Source Register Entry",
                "fieldtype": "Link",
                "options": REGISTER_DOCTYPE,
            },
            {
                "fieldname": "remarks",
                "label": "Remarks",
                "fieldtype": "Small Text",
            },
        ],
    })
    doc.insert(ignore_permissions=True)


def _add_party_table_field(parent_doctype):
    """Attach the Party Document child table to Customer / Supplier."""
    if frappe.db.exists(
        "Custom Field", {"dt": parent_doctype, "fieldname": PARTY_TABLE_FIELDNAME}
    ):
        return

    # place after a stable standard section; adjust insert_after if you prefer
    frappe.get_doc({
        "doctype": "Custom Field",
        "dt": parent_doctype,
        "fieldname": PARTY_TABLE_FIELDNAME,
        "label": "Party Documents",
        "fieldtype": "Table",
        "options": PARTY_DOC_DOCTYPE,
        "insert_after": "customer_details" if parent_doctype == "Customer" else "supplier_details",
    }).insert(ignore_permissions=True)


# =============================================================================
# PART B — MISSING-DATE GUARD + party attachment hook
#   hooks.py:
#     doc_events = {
#         "Document Register": {
#             "before_save": "darkbrown.api.doc_intake_phase2.register_before_save",
#             "on_update":   "darkbrown.api.doc_intake_phase2.register_on_update",
#         }
#     }
# =============================================================================

def register_before_save(doc, method=None):
    """Block transition to Pushed while confirmed cheques lack dates."""
    if doc.get(REGISTER_STATUS_FIELD) != "Pushed":
        return

    before = doc.get_doc_before_save()
    if before and before.get(REGISTER_STATUS_FIELD) == "Pushed":
        return  # already pushed, not a fresh transition

    if doc.get(REGISTER_DOCTYPE_FIELD) != "Cheque Batch":
        return

    missing = _rows_missing_dates(doc)
    if missing:
        frappe.throw(
            _("Cannot push: {0} confirmed cheque(s) have no cheque date — rows {1}. "
              "Fill the date from the scanned cheque, or untick Confirmed to exclude the row.")
            .format(len(missing), ", ".join(missing)),
            title=_("Missing Cheque Dates"),
        )


def _rows_missing_dates(doc):
    missing = []
    for row in doc.get(REGISTER_CHEQUES_TABLE) or []:
        if row.get(ROW_CONFIRMED_FIELD) and not row.get(ROW_CHEQUE_DATE_FIELD):
            missing.append(
                "#{0} ({1})".format(row.idx, row.get(ROW_CHEQUE_NO_FIELD) or "no number")
            )
    return missing


@frappe.whitelist()
def check_missing_dates(register_name):
    """Optional preflight for the /doc-intake page: call before enabling Push.
    Returns {"ok": bool, "missing": [labels]} so the UI can amber-flag rows."""
    guard(MD, DOC, ACC)
    doc = frappe.get_doc(REGISTER_DOCTYPE, register_name)
    if doc.get(REGISTER_DOCTYPE_FIELD) != "Cheque Batch":
        return {"ok": True, "missing": []}
    missing = _rows_missing_dates(doc)
    return {"ok": not missing, "missing": missing}


def register_on_update(doc, method=None):
    """When an identity/contract document reaches Pushed, file it on the party."""
    if doc.get(REGISTER_STATUS_FIELD) != "Pushed":
        return
    if doc.get(REGISTER_DOCTYPE_FIELD) not in PARTY_ATTACHABLE_TYPES:
        return

    before = doc.get_doc_before_save()
    if before and before.get(REGISTER_STATUS_FIELD) == "Pushed":
        return  # avoid duplicate filing on subsequent saves

    try:
        attach_register_to_party(doc.name)
    except Exception:
        # never block the push itself over the filing step; log for follow-up
        frappe.log_error(
            title="Party Document filing failed",
            message=frappe.get_traceback(),
        )


@frappe.whitelist()
def attach_register_to_party(register_name):
    """Append a Party Document row on the linked Customer/Supplier.
    Idempotent per (party, source_register)."""
    guard(MD, DOC, ACC)
    reg = frappe.get_doc(REGISTER_DOCTYPE, register_name)

    party_doctype, party_name = None, None
    if reg.get(REGISTER_CUSTOMER_FIELD):
        party_doctype, party_name = "Customer", reg.get(REGISTER_CUSTOMER_FIELD)
    elif reg.get(REGISTER_SUPPLIER_FIELD):
        party_doctype, party_name = "Supplier", reg.get(REGISTER_SUPPLIER_FIELD)

    if not party_name:
        return {"attached": False, "reason": "No customer/supplier linked on the register entry."}

    party = frappe.get_doc(party_doctype, party_name)

    for row in party.get(PARTY_TABLE_FIELDNAME) or []:
        if row.get("source_register") == reg.name:
            return {"attached": False, "reason": "Already filed on {0}.".format(party_name)}

    party.append(PARTY_TABLE_FIELDNAME, {
        "document_type": reg.get(REGISTER_DOCTYPE_FIELD),
        "document_no": reg.get(REGISTER_DOC_NO_FIELD),
        "issue_date": reg.get(REGISTER_ISSUE_FIELD),
        "expiry_date": reg.get(REGISTER_EXPIRY_FIELD),
        "file": reg.get(REGISTER_SOURCE_FILE_FIELD),
        "source_register": reg.name,
    })
    party.save(ignore_permissions=True)
    return {"attached": True, "party": party_name}


# =============================================================================
# PART C — MARK CLEARED v2: clearance + Payment Entry reconciliation
#   Point the PDC Cheque "Mark Cleared" dialog at:
#       darkbrown.api.doc_intake_phase2.mark_cleared_v2
# =============================================================================

@frappe.whitelist()
def mark_cleared_v2(pdc_name, clearance_date, create_payment=1):
    guard(MD, ACC)
    create_payment = frappe.utils.cint(create_payment)
    clearance_date = getdate(clearance_date)

    pdc = frappe.get_doc(PDC_DOCTYPE, pdc_name)

    if pdc.get(PDC_STATUS_FIELD) == "Cleared":
        frappe.throw(_("{0} is already Cleared.").format(pdc_name))

    amount = flt(pdc.get(PDC_AMOUNT_FIELD))
    if amount <= 0:
        frappe.throw(_("Cheque amount must be greater than zero."))

    result = {
        "pdc": pdc_name,
        "cheque_date_backfilled": False,
        "payment_entry": None,
        "allocated": [],
        "unallocated": 0.0,
    }

    # --- backfill missing cheque date (cheque #13 scenario) ---
    if not pdc.get(PDC_CHEQUE_DATE_FIELD):
        pdc.set(PDC_CHEQUE_DATE_FIELD, clearance_date)
        pdc.add_comment(
            "Comment",
            _("Cheque date was blank at clearance; set to clearance date {0}. "
              "Verify against the physical cheque.").format(clearance_date),
        )
        result["cheque_date_backfilled"] = True

    pdc.set(PDC_STATUS_FIELD, "Cleared")
    pdc.set(PDC_CLEARED_DATE_FIELD, clearance_date)

    # --- payment entry ---
    if create_payment:
        pe = _make_payment_entry(pdc, clearance_date, amount, result)
        result["payment_entry"] = pe.name
        if pdc.meta.has_field(PDC_PAYMENT_ENTRY_FIELD):
            pdc.set(PDC_PAYMENT_ENTRY_FIELD, pe.name)

    pdc.save(ignore_permissions=True)
    frappe.db.commit()
    return result


def _make_payment_entry(pdc, clearance_date, amount, result):
    from erpnext.accounts.party import get_party_account

    incoming = pdc.get(PDC_DIRECTION_FIELD) == DIRECTION_INCOMING

    if incoming:
        party_type = "Customer"
        party = _get_customer_from_pdc(pdc)
        invoice_doctype = "Sales Invoice"
        party_field = "customer"
        payment_type = "Receive"
    else:
        party_type = "Supplier"
        party = _get_supplier_from_pdc(pdc)
        invoice_doctype = "Purchase Invoice"
        party_field = "supplier"
        payment_type = "Pay"

    if not party:
        frappe.throw(
            _("Could not resolve the {0} for this cheque — check the agreement link.")
            .format(party_type.lower())
        )

    bank_account = frappe.get_cached_value("Company", COMPANY, "default_bank_account")
    if not bank_account:
        frappe.throw(
            _("Set a Default Bank Account on Company {0} before creating clearance payments.")
            .format(COMPANY)
        )

    party_account = get_party_account(party_type, party, COMPANY)

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = payment_type
    pe.company = COMPANY
    pe.posting_date = clearance_date
    pe.mode_of_payment = "Cheque"
    pe.party_type = party_type
    pe.party = party
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.source_exchange_rate = 1
    pe.target_exchange_rate = 1
    pe.reference_no = pdc.get(PDC_CHEQUE_NO_FIELD)
    pe.reference_date = pdc.get(PDC_CHEQUE_DATE_FIELD) or clearance_date

    if incoming:
        pe.paid_from = party_account          # Debtors
        pe.paid_to = bank_account
    else:
        pe.paid_from = bank_account
        pe.paid_to = party_account            # Creditors

    pe.paid_from_account_currency = CURRENCY
    pe.paid_to_account_currency = CURRENCY

    # --- FIFO allocation against outstanding invoices ---
    remaining = amount
    invoices = frappe.get_all(
        invoice_doctype,
        filters={
            party_field: party,
            "docstatus": 1,
            "outstanding_amount": [">", 0],
            "company": COMPANY,
        },
        fields=["name", "outstanding_amount", "posting_date", "due_date", "grand_total"],
        order_by="due_date asc, posting_date asc",
    )

    for inv in invoices:
        if remaining <= 0:
            break
        alloc = min(remaining, flt(inv.outstanding_amount))
        pe.append("references", {
            "reference_doctype": invoice_doctype,
            "reference_name": inv.name,
            "total_amount": flt(inv.grand_total),
            "outstanding_amount": flt(inv.outstanding_amount),
            "allocated_amount": alloc,
        })
        result["allocated"].append({"invoice": inv.name, "amount": alloc})
        remaining -= alloc

    result["unallocated"] = flt(remaining)

    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe


def _get_customer_from_pdc(pdc):
    tra = pdc.get(PDC_TRA_FIELD)
    if not tra:
        return None
    return frappe.db.get_value("Tenant Rental Agreement", tra, TRA_CUSTOMER_FIELD)


def _get_supplier_from_pdc(pdc):
    llc = pdc.get(PDC_LLC_FIELD)
    if not llc:
        return None
    return frappe.db.get_value("Landlord Contract", llc, LLC_SUPPLIER_FIELD)


# =============================================================================
# WIRING (three one-line edits outside this file)
# =============================================================================
# 1) patches.txt  — under [post_model_sync]:
#       darkbrown.api.doc_intake_phase2.execute
#
# 2) hooks.py — merge into your existing doc_events dict:
#       doc_events = {
#           "Document Register": {
#               "before_save": "darkbrown.api.doc_intake_phase2.register_before_save",
#               "on_update":   "darkbrown.api.doc_intake_phase2.register_on_update",
#           },
#       }
#
# 3) PDC Cheque client script — point the existing Mark Cleared dialog at
#    the new endpoint (keep your dialog UI as-is):
#
#       frappe.call({
#           method: "darkbrown.api.doc_intake_phase2.mark_cleared_v2",
#           args: {
#               pdc_name: frm.doc.name,
#               clearance_date: values.clearance_date,
#               create_payment: 1
#           },
#           callback: function (r) {
#               if (!r.message) return;
#               let m = r.message;
#               let msg = "Cheque cleared.";
#               if (m.payment_entry) msg += "<br>Payment Entry: <b>" + m.payment_entry + "</b>";
#               if (m.allocated.length) {
#                   msg += "<br>Allocated to: " +
#                       m.allocated.map(a => a.invoice + " (QAR " + a.amount + ")").join(", ");
#               }
#               if (m.unallocated > 0) msg += "<br>Unallocated (advance): QAR " + m.unallocated;
#               if (m.cheque_date_backfilled) msg += "<br>⚠ Cheque date was blank — set to clearance date.";
#               frappe.msgprint(msg);
#               frm.reload_doc();
#           }
#       });
# =============================================================================
