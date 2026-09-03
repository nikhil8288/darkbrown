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


# ------------------------------------------------------------------ the vault

#: What the register's own status values are called on the screen. Kept
#: identical to app.DOC_STATE so a document does not change its apparent state
#: between the intake queue and the vault.
VAULT_STATE = {"Draft": "Needs review", "Extracting": "Needs review",
               "Needs Review": "Needs review", "Confirmed": "Validated",
               "Rejected": "Flagged", "Superseded": "Superseded"}

#: The vault carries two things: the register, which is everything filed, and
#: the archive, which is what intake pushed through with a permanent title.
#: Both are documents a person is looking for, so both are searchable here.
VAULT_LIMIT = 400


def _short(user):
    if not user or user == "Administrator":
        return "System"
    full = frappe.db.get_value("User", user, "full_name") or user
    bits = full.split()
    return bits[0] + (" " + bits[-1][0] + "." if len(bits) > 1 else "")


def _size(file_url):
    """File size as the vault shows it, or an em dash when the File row is
    gone. A missing size is not an error worth surfacing — the document is
    still findable, which is what the screen is for."""
    if not file_url:
        return "—"
    size = frappe.db.get_value("File", {"file_url": file_url}, "file_size")
    if not size:
        return "—"
    size = flt(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return "—"


def _entity(party_type, party, building, unit, agreement=None):
    if agreement:
        return "Agreement"
    if unit:
        return "Unit"
    if party_type == "Customer":
        return "Tenant"
    if party_type == "Supplier":
        return "Landlord"
    if building:
        return "Building"
    return "Unfiled"


@frappe.whitelist()
def vault(q=None, ty=None, ent=None, st=None, limit=None):
    """Everything on the register and in the archive, filed and findable.

    The screen has always had filters. It filtered a generated list. Filtering
    happens here now, on records, and the counts the screen prints are counts
    of things that exist.
    """
    guard(MD, GM, ACC, DOC)
    limit = int(limit or VAULT_LIMIT)

    reg = frappe.get_all(
        "Document Register",
        fields=["name", "source_file", "document_type", "status", "party",
                "party_type", "building", "unit", "document_no", "expiry_date",
                "owner", "modified", "creation"],
        order_by="modified desc", limit=limit)

    arch = frappe.get_all(
        "Document Archive",
        fields=["name", "file", "document_type", "archive_title", "party",
                "party_type", "building", "unit", "id_number", "archived_on",
                "archived_by", "original_filename", "source_register",
                "owner", "modified"],
        order_by="modified desc", limit=limit)

    # A register row that was archived is the same document twice. The archive
    # copy wins: it is the one with the permanent title and the filed name.
    archived_from = {a.source_register for a in arch if a.source_register}

    rows = []
    for d in reg:
        if d.name in archived_from:
            continue
        rows.append({
            "id": d.name,
            "f": (d.source_file or "").split("/")[-1] or "—",
            "ty": d.document_type or "Unknown",
            "link": str(d.party or d.building or "—"),
            "ent": _entity(d.party_type, d.party, d.building, d.unit),
            "filed": str(d.modified)[:10] if d.modified else "",
            "by": _short(d.owner),
            "size": _size(d.source_file),
            "st": VAULT_STATE.get(d.status, d.status or "Needs review"),
            "url": d.source_file or "",
            "no": d.document_no or "",
            "exp": str(d.expiry_date) if d.expiry_date else "",
            "src": "Register",
        })
    for a in arch:
        rows.append({
            "id": a.name,
            "f": (a.original_filename
                  or (a.file or "").split("/")[-1] or a.archive_title or "—"),
            "ty": a.document_type or "Unknown",
            "link": str(a.party or a.building or "—"),
            "ent": _entity(a.party_type, a.party, a.building, a.unit),
            "filed": str(a.archived_on or a.modified)[:10],
            "by": _short(a.archived_by or a.owner),
            "size": _size(a.file),
            "st": "Validated",
            "url": a.file or "",
            "no": a.id_number or "",
            "exp": "",
            "src": "Archive",
        })

    total = len(rows)

    def keep(r):
        if ty and not str(ty).startswith("All") and r["ty"] != ty:
            return False
        if ent and not str(ent).startswith("All") and r["ent"] != ent:
            return False
        if st and not str(st).startswith("All") and r["st"] != st:
            return False
        if q:
            hay = " ".join([r["f"], r["ty"], r["link"], r["ent"], r["no"],
                            r["id"]]).lower()
            if str(q).lower() not in hay:
                return False
        return True

    matched = [r for r in rows if keep(r)]
    matched.sort(key=lambda r: r["filed"], reverse=True)
    return {
        "rows": matched,
        "total": total,
        "validated": sum(1 for r in rows if r["st"] == "Validated"),
        "review": sum(1 for r in rows if r["st"] == "Needs review"),
        "types": sorted({r["ty"] for r in rows}),
        "filers": sorted({r["by"] for r in rows}),
        "capped": total >= limit,
    }


@frappe.whitelist()
def preview(document):
    """Where the file actually is, so the viewer can open it.

    Returns the URL rather than the bytes. The file is served by Frappe with
    its own permission check on the way out, which is the check that should be
    deciding this — not one written again here and drifting from it.
    """
    guard(MD, GM, ACC, DOC)
    for doctype, field in (("Document Register", "source_file"),
                           ("Document Archive", "file")):
        if frappe.db.exists(doctype, document):
            url = frappe.db.get_value(doctype, document, field)
            if not url:
                frappe.throw(_("No file is attached to that record."))
            return {"url": url, "doctype": doctype, "name": document}
    frappe.throw(_("That document is not on the register."))


# --------------------------------------------------- files on a record
#
# The second way in. Intake exists for documents that have to be *read* — a
# QID whose number and expiry matter, a lease whose rent matters — and it
# costs a rasterise, an OCR pass and a human review before anything is on
# file. Most paperwork is not like that. A landlord's bank letter, a floor
# plan, a signed acknowledgement: nobody needs a field read off it, somebody
# needs to be able to find it against the building or the door it belongs to.
#
# So this path uploads the file, files it against the Building or the Unit,
# and stops. No extractor is named, no confidence is recorded, and no review
# queue is joined, because there is no extracted claim to review — a person
# said what this is and put it where it goes. That is why the register row is
# written Confirmed rather than Needs Review: Needs Review would ask
# Documentation to validate a reading that was never made.


def _file_types():
    """The register's own type list, read off the meta rather than repeated
    here. A type added to the DocType appears on the form without a code
    change, and a type removed cannot be written by this path."""
    field = frappe.get_meta("Document Register").get_field("document_type")
    return [o for o in (field.options or "").split("\n") if o]


@frappe.whitelist()
def file_types():
    guard(MD, GM, ACC, DOC)
    return _file_types()


@frappe.whitelist()
def save_files(payload):
    """File already-uploaded files against a building or a unit.

    The upload itself happened before this call, against the Building or Unit
    record, so the bytes are already attached where they belong. What this
    adds is the register row that makes them findable from the vault and from
    the screen for that record.
    """
    guard(MD, GM, ACC, DOC)
    data = frappe.parse_json(payload) or {}

    urls = [u for u in (data.get("files") or []) if u]
    if not urls:
        frappe.throw(_("No file was uploaded, so there is nothing to file."))

    building = (data.get("building") or "").strip() or None
    unit = (data.get("unit") or "").strip() or None

    if unit:
        if not frappe.db.exists("Unit", unit):
            frappe.throw(_("No unit called {0}.").format(unit))
        # A unit file is a building file too. Deriving the building here is
        # what lets the building screen show everything filed under its doors
        # without the caller having to send both.
        building = frappe.db.get_value("Unit", unit, "building") or building
    elif building:
        if not frappe.db.exists("Building", building):
            frappe.throw(_("No building called {0}.").format(building))
    else:
        frappe.throw(_("A file is filed against a building or a unit. This "
                       "one named neither."))

    kind = (data.get("type") or "Other").strip()
    if kind not in _file_types():
        kind = "Other"

    created = []
    for url in urls:
        doc = frappe.get_doc({
            "doctype": "Document Register",
            "source_file": url,
            "document_type": kind,
            "status": "Confirmed",
            "building": building,
            "unit": unit,
            "page_count": 0,
            "issue_date": data.get("issue_date") or None,
            "expiry_date": data.get("expiry_date") or None,
        })
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        created.append(doc.name)

    return {"filed": len(created), "documents": created,
            "building": building, "unit": unit, "type": kind}


def _file_row(name, url, kind, status, on, when, by, src):
    return {
        "id": name,
        "f": (url or "").split("/")[-1] or "—",
        "ty": kind or "Unknown",
        "st": status,
        "on": on,
        "when": str(when)[:10] if when else "",
        "by": _short(by),
        "size": _size(url),
        "url": url or "",
        "src": src,
    }


@frappe.whitelist()
def files(building=None, unit=None):
    """Everything on file against one building, or one unit.

    Asked for a building this includes the files filed against its units, and
    says which door each one came from. A tenancy contract filed on unit 302
    is a document about that building, and somebody looking at the building
    for it should not have to know which unit it went to first.
    """
    guard(MD, GM, ACC, DOC)
    building = (building or "").strip() or None
    unit = (unit or "").strip() or None
    if not (building or unit):
        frappe.throw(_("Which building or unit?"))

    if unit:
        or_filters = {"unit": unit}
    else:
        units = frappe.get_all("Unit", filters={"building": building},
                               pluck="name")
        or_filters = {"building": building}
        if units:
            or_filters["unit"] = ["in", units]

    reg = frappe.get_all(
        "Document Register", or_filters=or_filters,
        fields=["name", "source_file", "document_type", "status", "building",
                "unit", "owner", "modified"],
        order_by="modified desc", limit=VAULT_LIMIT)

    arch = frappe.get_all(
        "Document Archive", or_filters=or_filters,
        fields=["name", "file", "document_type", "building", "unit",
                "archived_on", "archived_by", "source_register", "owner",
                "modified"],
        order_by="modified desc", limit=VAULT_LIMIT)

    # The archive copy of a register row is the same document twice. The
    # archive wins, exactly as it does in the vault.
    archived_from = {a.source_register for a in arch if a.source_register}

    rows = []
    for d in reg:
        if d.name in archived_from:
            continue
        rows.append(_file_row(
            d.name, d.source_file, d.document_type,
            VAULT_STATE.get(d.status, d.status or "Needs review"),
            d.unit or "Building", d.modified, d.owner, "Register"))
    for a in arch:
        rows.append(_file_row(
            a.name, a.file, a.document_type, "Validated",
            a.unit or "Building", a.archived_on or a.modified,
            a.archived_by or a.owner, "Archive"))

    rows.sort(key=lambda r: r["when"], reverse=True)
    return {
        "rows": rows,
        "total": len(rows),
        "on_units": sum(1 for r in rows if r["on"] != "Building"),
        "types": _file_types(),
    }
