"""The document vault.

Every document that matters to a party or a building is registered once and
referenced everywhere else. Nothing is filed twice, and a document that
replaces another says so rather than silently sitting alongside it.

Extraction is not done here. A document arrives with whatever a human or an
extractor put on it, and this module is concerned with what happens next:
reviewing it, filing it against the right party, and tracking what expires.
"""

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, date_diff, add_days
from darkbrown.guards import guard, ACC, DOC, GM, MD

PARTY_FIELD = {"Customer": "db_documents", "Supplier": "db_documents"}


@frappe.whitelist()
def register(payload):
    """File a document. It lands needing review unless it arrives confirmed."""
    guard(MD, GM, ACC, DOC)
    data = frappe.parse_json(payload)

    doc = frappe.get_doc({
        "doctype": "Document Register",
        "source_file": data.get("file"),
        "document_type": data.get("type") or "Unknown",
        "status": data.get("status") or "Needs Review",
        "page_count": int(data.get("pages") or 0),
        "party_type": data.get("party_type"),
        "party": data.get("party"),
        "building": data.get("building"),
        "unit": data.get("unit"),
        "issue_date": data.get("issue_date"),
        "expiry_date": data.get("expiry_date"),
        "document_no": data.get("document_no"),
        "extracted_json": data.get("extracted"),
        "extraction_confidence": flt(data.get("confidence")),
        "extractor_model": data.get("model"),
        "extracted_on": frappe.utils.now() if data.get("extracted") else None,
    })
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True)

    if doc.expiry_date:
        doc.db_set("days_to_expiry", date_diff(doc.expiry_date, today()),
                   update_modified=False)

    return {"document": doc.name, "status": doc.status}


@frappe.whitelist()
def review(document, decision, payload=None):
    """Confirm or reject a document.

    Confirming does two things beyond changing a status: it files the document
    against its party so it shows on that party's record, and it supersedes
    any earlier document of the same type for the same party. A QID that has
    been renewed should not leave the old one looking current.
    """
    guard(MD, GM, DOC)
    data = frappe.parse_json(payload) if payload else {}
    doc = frappe.get_doc("Document Register", document)

    if doc.status in ("Confirmed", "Superseded"):
        frappe.throw(_("{0} is already {1}.").format(document, doc.status))

    if decision == "reject":
        reason = (data.get("reason") or "").strip()
        if not reason:
            frappe.throw(_("A rejection needs a reason."))
        doc.status = "Rejected"
        doc.rejection_reason = reason
        doc.reviewed_by = frappe.session.user
        doc.reviewed_on = frappe.utils.now()
        doc.save(ignore_permissions=True)
        return {"document": doc.name, "status": doc.status}

    for field in ("document_type", "document_no", "issue_date",
                  "expiry_date", "party_type", "party", "building", "unit"):
        if data.get(field):
            doc.set(field, data[field])

    doc.status = "Confirmed"
    doc.reviewed_by = frappe.session.user
    doc.reviewed_on = frappe.utils.now()
    if doc.expiry_date:
        doc.days_to_expiry = date_diff(doc.expiry_date, today())
    doc.save(ignore_permissions=True)

    superseded = _supersede(doc)
    _file_against_party(doc)

    return {"document": doc.name, "status": doc.status,
            "superseded": superseded}


def _supersede(doc):
    """An earlier document of the same type for the same party is history."""
    if not (doc.party and doc.document_type):
        return None
    older = frappe.get_all(
        "Document Register",
        filters={"party": doc.party, "document_type": doc.document_type,
                 "status": "Confirmed", "name": ["!=", doc.name]},
        fields=["name", "issue_date"], order_by="issue_date desc")
    out = []
    for o in older:
        if doc.issue_date and o.issue_date and getdate(o.issue_date) > getdate(
                doc.issue_date):
            continue
        frappe.db.set_value("Document Register", o.name, "status", "Superseded")
        out.append(o.name)
    if out:
        doc.db_set("supersedes", out[0], update_modified=False)
    return out


def _file_against_party(doc):
    """Put the document on the party's own record."""
    field = PARTY_FIELD.get(doc.party_type)
    if not (field and doc.party):
        return
    if not frappe.db.exists(doc.party_type, doc.party):
        return
    party = frappe.get_doc(doc.party_type, doc.party)
    for row in party.get(field) or []:
        if row.document_register == doc.name:
            return
    party.append(field, {
        "document_type": doc.document_type,
        "document_no": doc.document_no,
        "issue_date": doc.issue_date,
        "expiry_date": doc.expiry_date,
        "status": "Valid",
        "file": doc.source_file,
        "document_register": doc.name,
    })
    party.flags.ignore_mandatory = True
    party.save(ignore_permissions=True)


@frappe.whitelist()
def expiring(days=None):
    """What lapses soon, and what has already lapsed.

    Sorted by how overdue it is, because an expired QID is a bigger problem
    than one expiring next month.
    """
    guard(MD, GM, ACC, DOC)
    window = int(days or 60)
    rows = frappe.get_all(
        "Document Register",
        filters={"status": "Confirmed", "expiry_date": ["is", "set"]},
        fields=["name", "document_type", "party_type", "party", "building",
                "document_no", "expiry_date"],
        order_by="expiry_date asc")
    out = []
    for r in rows:
        left = date_diff(r.expiry_date, today())
        if left > window:
            continue
        out.append({
            "id": r.name,
            "ty": r.document_type,
            "party": r.party or r.building or "—",
            "no": r.document_no or "—",
            "expiry": getdate(r.expiry_date).strftime("%d %b %y"),
            "days": left,
            "st": "Expired" if left < 0 else "Expiring",
        })
    return out


@frappe.whitelist()
def missing_for(party_type, party):
    """What this party is required to have on file but does not.

    The requirement list is configuration, not code, so it can change without
    a deploy.
    """
    guard(MD, GM, ACC, DOC)
    applies = "Tenant" if party_type == "Customer" else "Landlord"
    required = frappe.get_all(
        "Document Requirement",
        filters={"applies_to": ["in", (applies, "Both")], "mandatory": 1},
        fields=["document_type", "expiry_tracked", "notice_days"])
    if not required:
        return []

    held = {d.document_type: d for d in frappe.get_all(
        "Document Register",
        filters={"party": party, "status": "Confirmed"},
        fields=["document_type", "expiry_date"])}

    out = []
    for r in required:
        have = held.get(r.document_type)
        if not have:
            out.append({"type": r.document_type, "why": "not on file"})
        elif r.expiry_tracked and have.expiry_date:
            left = date_diff(have.expiry_date, today())
            if left < 0:
                out.append({"type": r.document_type, "why": "expired"})
            elif left <= int(r.notice_days or 30):
                out.append({"type": r.document_type,
                            "why": f"expires in {left} days"})
    return out


def nightly():
    """Keep days_to_expiry honest so the queue sorts correctly at boot."""
    for d in frappe.get_all(
            "Document Register",
            filters={"status": "Confirmed", "expiry_date": ["is", "set"]},
            fields=["name", "expiry_date", "days_to_expiry"]):
        left = date_diff(d.expiry_date, today())
        if left != d.days_to_expiry:
            frappe.db.set_value("Document Register", d.name,
                                "days_to_expiry", left, update_modified=False)
    frappe.db.commit()
