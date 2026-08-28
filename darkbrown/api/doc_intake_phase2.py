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
#    PART C — mark_cleared_v2: clears a Cheque, backfills a missing
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
    "Head Lease",
    "Owner Contract",
    "Utility/Other",
)

# Cheque
PDC_DOCTYPE = "Cheque"
PDC_STATUS_FIELD = "status"                      # Received/Deposited/Presented/Cleared/Returned/Replaced/Cancelled
PDC_DIRECTION_FIELD = "direction"                # "Incoming (from Tenant)" / "Outgoing (to Landlord)"
PDC_CHEQUE_NO_FIELD = "cheque_no"
PDC_CHEQUE_DATE_FIELD = "cheque_date"
PDC_CLEARED_DATE_FIELD = "cleared_on"
PDC_AMOUNT_FIELD = "amount"
PDC_BANK_FIELD = "bank"
PDC_TRA_FIELD = "tenancy_agreement"             # Link -> Tenancy Agreement
PDC_LLC_FIELD = "head_lease"                    # Link -> Head Lease
PDC_PAYMENT_ENTRY_FIELD = "payment_entry"        # optional Link -> Payment Entry (skipped if absent)

DIRECTION_INCOMING = "Incoming"

# Party fields on the agreement doctypes
TRA_CUSTOMER_FIELD = "tenant"                   # Tenancy Agreement -> Customer
LLC_SUPPLIER_FIELD = "landlord"                 # Head Lease -> Supplier

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
                "options": "QID/National ID\nPassport\nTenant Contract\nHead Lease\nOwner Contract\nCheque Batch\nUtility/Other",
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
#   Point the Cheque "Mark Cleared" dialog at:
#       darkbrown.api.doc_intake_phase2.mark_cleared_v2
# =============================================================================

@frappe.whitelist()
def mark_cleared_v2(pdc_name, clearance_date, create_payment=1):
    """Deprecated. Delegates to api.finance.clear_cheque.

    This was the fourth implementation of "clear a cheque" in the app, and the
    most dangerous of them: its DIRECTION_INCOMING constant was
    "Incoming (from Tenant)" while the doctype option is plain "Incoming", so
    the incoming test was always False and every TENANT cheque would have been
    posted as an outgoing landlord payment. It also wrote cleared_date, a field
    that does not exist, so the clearance date was silently discarded, and it
    submitted its Payment Entry immediately while the other engines drafted.

    api.finance is the single engine. create_payment is accepted and ignored:
    a clearing that does not post a receipt is what the register-versus-ledger
    drift was made of.
    """
    from darkbrown.api import finance
    res = finance.clear_cheque(pdc_name, on=clearance_date)
    return {
        "pdc": res["cheque"],
        "payment_entry": res.get("payment_entry"),
        "cheque_date_backfilled": False,
        "allocated": [],
        "unallocated": 0.0,
    }


def _get_customer_from_pdc(pdc):
    tra = pdc.get(PDC_TRA_FIELD)
    if not tra:
        return None
    return frappe.db.get_value("Tenancy Agreement", tra, TRA_CUSTOMER_FIELD)


def _get_supplier_from_pdc(pdc):
    llc = pdc.get(PDC_LLC_FIELD)
    if not llc:
        return None
    return frappe.db.get_value("Head Lease", llc, LLC_SUPPLIER_FIELD)


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
# 3) Cheque client script — point the existing Mark Cleared dialog at
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
