"""Every building carries its own cost centre so that head-lease rent, utilities,
maintenance and the sublease income booked against it roll up to a per-building
spread without any manual tagging. Ported from V1 and re-fitted to the V2 schema,
where Building is named by field:building_name and holds a company link.
"""

import frappe
from frappe import _


def _label(doc):
    return (doc.get("building_name") or doc.name or "").strip()


def _company(doc=None):
    if doc and doc.get("company"):
        return doc.company
    return frappe.defaults.get_user_default("Company")


def _root_cost_center(company):
    root = frappe.db.get_value(
        "Cost Center",
        {"company": company, "is_group": 1, "parent_cost_center": ["is", "not set"]},
        "name",
    )
    if not root:
        root = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
    return root


def _cc_name(label, company):
    abbr = frappe.get_cached_value("Company", company, "abbr")
    return f"{label} - {abbr}"


def create_building_cost_center(doc, method=None):
    company = _company(doc)
    if not company:
        frappe.msgprint(_("No company set; cost centre not created."), alert=True)
        return

    label = _label(doc)
    name = _cc_name(label, company)

    if frappe.db.exists("Cost Center", name):
        frappe.db.set_value("Building", doc.name, "cost_center", name, update_modified=False)
        return

    root = _root_cost_center(company)
    if not root:
        frappe.msgprint(_("No group cost centre found for {0}; skipping.").format(company), alert=True)
        return

    cc = frappe.get_doc({
        "doctype": "Cost Center",
        "cost_center_name": label,
        "parent_cost_center": root,
        "company": company,
        "is_group": 0,
    })
    cc.insert(ignore_permissions=True)
    frappe.db.set_value("Building", doc.name, "cost_center", cc.name, update_modified=False)


def sync_building_cost_center(doc, method=None):
    """Keep the cost centre label in step when the building is renamed in place."""
    before = doc.get_doc_before_save()
    if not before:
        return

    old_label, new_label = _label(before), _label(doc)
    if old_label == new_label:
        return

    company = _company(doc)
    old_name = _cc_name(old_label, company)
    if not frappe.db.exists("Cost Center", old_name):
        return

    new_name = _cc_name(new_label, company)
    frappe.db.set_value("Cost Center", old_name, "cost_center_name", new_label)
    frappe.rename_doc("Cost Center", old_name, new_name, force=True, ignore_permissions=True)
    frappe.db.set_value("Building", doc.name, "cost_center", new_name, update_modified=False)


def sync_after_rename(doc, method=None, old_name=None, new_name=None, merge=False):
    create_building_cost_center(doc)


def guard_cost_center_delete(doc, method=None):
    """A cost centre with ledger entries against it must not disappear with the building."""
    if not doc.cost_center:
        return
    if frappe.db.exists("GL Entry", {"cost_center": doc.cost_center, "is_cancelled": 0}):
        frappe.throw(
            _("{0} has ledger entries posted against it and cannot be removed. Mark the building Exited instead.")
            .format(doc.cost_center)
        )
    frappe.delete_doc("Cost Center", doc.cost_center, ignore_permissions=True, force=False)
