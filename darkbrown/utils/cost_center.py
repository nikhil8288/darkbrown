import frappe


def _cc_label(doc):
    # Prefer the human-readable building_name; fall back to record ID.
    # Robust whether autoname is field:building_name or a number series.
    return (doc.get("building_name") or doc.name).strip()


def _root_cost_center():
    # The group cost center all buildings sit under (the company root).
    company = frappe.defaults.get_user_default("Company") or "DarkBrown RealEstate"
    root = frappe.db.get_value(
        "Cost Center",
        {"company": company, "is_group": 1, "parent_cost_center": ["is", "not set"]},
        "name",
    )
    if not root:
        # Fallback: the company's main group cost center
        root = frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 1}, "name"
        )
    return root, company


def create_building_cost_center(doc, method=None):
    company = frappe.defaults.get_user_default("Company") or "DarkBrown RealEstate"
    label = _cc_label(doc)
    cc_name = f"{label} - {frappe.get_cached_value('Company', company, 'abbr')}"

    if frappe.db.exists("Cost Center", cc_name):
        return  # already exists, don't duplicate

    root, company = _root_cost_center()
    if not root:
        frappe.msgprint(
            "No group Cost Center found for the company; skipping auto-creation.",
            alert=True,
        )
        return

    cc = frappe.get_doc({
        "doctype": "Cost Center",
        "cost_center_name": label,
        "parent_cost_center": root,
        "company": company,
        "is_group": 0,
    })
    cc.insert(ignore_permissions=True)
    frappe.db.commit()


def sync_building_cost_center_rename(doc, method=None):
    before = doc.get_doc_before_save()
    if not before:
        return
    old_label = _cc_label(before)
    new_label = _cc_label(doc)
    if old_label == new_label:
        return  # name didn't change

    company = frappe.defaults.get_user_default("Company") or "DarkBrown RealEstate"
    abbr = frappe.get_cached_value("Company", company, "abbr")
    old_cc = f"{old_label} - {abbr}"
    new_cc = f"{new_label} - {abbr}"

    if frappe.db.exists("Cost Center", old_cc) and not frappe.db.exists("Cost Center", new_cc):
        frappe.rename_doc("Cost Center", old_cc, new_cc, force=True)
        frappe.db.set_value("Cost Center", new_cc, "cost_center_name", new_label)
        frappe.db.commit()


def handle_building_cost_center_delete(doc, method=None):
    company = frappe.defaults.get_user_default("Company") or "DarkBrown RealEstate"
    abbr = frappe.get_cached_value("Company", company, "abbr")
    cc = f"{_cc_label(doc)} - {abbr}"

    if not frappe.db.exists("Cost Center", cc):
        return

    # Never hard-delete a cost center with accounting history — disable instead.
    has_gl = frappe.db.exists("GL Entry", {"cost_center": cc})
    if has_gl:
        frappe.db.set_value("Cost Center", cc, "disabled", 1)
        frappe.db.commit()
        frappe.msgprint(
            f"Cost Center '{cc}' has accounting history and was disabled, not deleted.",
            alert=True,
        )
    else:
        frappe.delete_doc("Cost Center", cc, ignore_permissions=True, force=True)
        frappe.db.commit()
