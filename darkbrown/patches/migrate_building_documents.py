"""Fold existing Building Document child-table rows into Document Register.

The Building Document child table was authored in the live UI, so exact
fieldnames are discovered from meta at runtime (fuzzy match on fieldname).
Originals are left intact. Idempotent: skips rows already migrated
(matched on building + title + reference).
"""

import frappe

CHILD_CANDIDATES = ["Building Document", "Building Documents"]


def _discover_child_doctypes():
    """Any child table that actually holds rows parented to Building,
    regardless of what it was named in the UI."""
    found = []
    for c in frappe.get_all("DocType", filters={"istable": 1},
                            pluck="name"):
        try:
            if frappe.db.count(c, {"parenttype": "Building"}):
                found.append(c)
        except Exception:
            continue
    return found


def execute():
    if not frappe.db.exists("DocType", "Document Register"):
        return

    candidates = [c for c in CHILD_CANDIDATES
                  if frappe.db.exists("DocType", c)]
    candidates += [c for c in _discover_child_doctypes()
                   if c not in candidates]

    total = 0
    for child_dt in candidates:
        fmap = _field_map(child_dt)
        # only migrate tables that look like document stores
        if not (fmap.get("file") or fmap.get("expiry")
                or fmap.get("type")):
            continue
        total += _migrate_table(child_dt, fmap)

    frappe.db.commit()
    print(f"migrate_building_documents: created {total} register entries")


def _migrate_table(child_dt, fmap):
    rows = frappe.get_all(child_dt,
                          fields=["name", "parent", "parenttype"] +
                                 list(set(fmap.values())),
                          filters={"parenttype": "Building"})
    created = 0
    for r in rows:
        doc_type = (r.get(fmap.get("type")) or "Other") if fmap.get("type") else "Other"
        ref = r.get(fmap.get("reference")) if fmap.get("reference") else None
        title = f"{r.parent} - {doc_type}"

        marker = f"Migrated from {child_dt} row {r.name}"
        if frappe.db.exists("Document Register", {"notes": marker}):
            continue

        reg = frappe.get_doc({
            "doctype": "Document Register",
            "title": title,
            "document_type": _map_type(doc_type),
            "link_doctype": "Building",
            "link_name": r.parent,
            "building": r.parent,
            "reference_no": ref,
            "language": _safe_lang(r.get(fmap.get("language"))
                                   if fmap.get("language") else None),
            "issue_date": r.get(fmap.get("issue")) if fmap.get("issue") else None,
            "expiry_date": r.get(fmap.get("expiry")) if fmap.get("expiry") else None,
            "file": r.get(fmap.get("file")) if fmap.get("file") else None,
            "notes": marker,
        })
        reg.insert(ignore_permissions=True)
        created += 1

    return created


def _field_map(child_dt):
    """Discover fieldnames on the UI-built child table by fuzzy match."""
    meta = frappe.get_meta(child_dt)
    fmap = {}
    for f in meta.fields:
        fn = f.fieldname.lower()
        if f.fieldtype == "Attach" and "file" not in fmap:
            fmap["file"] = f.fieldname
        elif "type" in fn and "type" not in fmap:
            fmap["type"] = f.fieldname
        elif ("language" in fn or fn == "lang") and "language" not in fmap:
            fmap["language"] = f.fieldname
        elif ("reference" in fn or fn == "ref_no") and "reference" not in fmap:
            fmap["reference"] = f.fieldname
        elif "issue" in fn and f.fieldtype == "Date" and "issue" not in fmap:
            fmap["issue"] = f.fieldname
        elif "expiry" in fn and f.fieldtype == "Date" and "expiry" not in fmap:
            fmap["expiry"] = f.fieldname
    return fmap


def _map_type(raw):
    """Map free-text/UI doc types onto Document Register select options."""
    options = ["Trade License", "Municipality Permit",
               "Civil Defence Certificate", "Title Deed",
               "Building Completion Certificate", "Landlord ID / CR",
               "Tenant QID", "Passport Copy", "Lease Contract Copy",
               "Cheque Copy", "Deposit Receipt", "Power of Attorney",
               "Insurance", "Utility Document"]
    raw_l = (raw or "").strip().lower()
    for o in options:
        if raw_l and (raw_l in o.lower() or o.lower() in raw_l):
            return o
    return "Other"


def _safe_lang(raw):
    return raw if raw in ("Arabic", "English", "Bilingual") else None
