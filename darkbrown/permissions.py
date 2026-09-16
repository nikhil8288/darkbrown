"""Server-side record and building scope for DarkBrown.

Frappe User Permissions remain the source of building assignments. Code in
this app sometimes uses ``get_all`` or ``ignore_permissions=True`` for internal
work, so every externally reachable path must also call these helpers.
"""

import frappe
from frappe import _


UNRESTRICTED_ROLES = {"Managing Director", "System Manager"}


def _scoped(user):
    """Return the explicit Building User Permissions for ``user``."""
    return [p.for_value for p in frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Building"},
        fields=["for_value"])]


def allowed_buildings(user=None):
    """Return an allowed-building set, or ``None`` for portfolio-wide access.

    MD, System Manager and Administrator are intentionally portfolio-wide.
    Other roles become building-scoped when Building User Permissions exist;
    this preserves current unassigned Accounts/Documentation/Maintenance
    workflows while making every explicit assignment authoritative server-side.
    """
    user = user or frappe.session.user
    if user == "Administrator":
        return None
    if set(frappe.get_roles(user)) & UNRESTRICTED_ROLES:
        return None
    assigned = {name for name in _scoped(user) if name}
    return assigned or None


def can_access_building(building, user=None):
    if not building:
        return True
    allowed = allowed_buildings(user)
    return allowed is None or building in allowed


def require_building_access(building, user=None):
    if not can_access_building(building, user=user):
        frappe.throw(_("You do not have access to that building."),
                     frappe.PermissionError)
    return building


def building_for_record(doctype, name=None, doc=None):
    """Resolve a record's building without trusting a client-supplied value."""
    if doc is None:
        doc = frappe.get_doc(doctype, name)
    building = getattr(doc, "building", None) or doc.get("building")
    if building:
        return building
    unit = getattr(doc, "unit", None) or doc.get("unit")
    if unit:
        return frappe.db.get_value("Unit", unit, "building")
    agreement = (getattr(doc, "tenancy_agreement", None)
                 or doc.get("tenancy_agreement"))
    if not agreement and doctype == "Agreement Amendment":
        agreement = getattr(doc, "agreement", None) or doc.get("agreement")
    if agreement:
        return frappe.db.get_value("Tenancy Agreement", agreement, "building")
    return None


def require_record_access(doc, permtype="read"):
    """Require both native DocType permission and DarkBrown building scope."""
    if not doc.has_permission(permtype):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    require_building_access(building_for_record(doc.doctype, doc=doc))
    return doc


def require_file_access(file_url):
    """Resolve a File and its attachment authorization before bytes are read."""
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    if not file_doc or not file_doc.get("name"):
        frappe.throw(_("File not found."))
    if not file_doc.has_permission("read"):
        frappe.throw(_("Not permitted to read that file."), frappe.PermissionError)
    attached_dt = file_doc.get("attached_to_doctype")
    attached_name = file_doc.get("attached_to_name")
    if attached_dt and attached_name:
        require_record_access(frappe.get_doc(attached_dt, attached_name), "read")
    return file_doc


def require_tenant_access(tenant, user=None):
    allowed = allowed_buildings(user)
    if allowed is None:
        return tenant
    if not frappe.db.exists("Tenancy Agreement", {
            "tenant": tenant, "building": ["in", sorted(allowed)]}):
        frappe.throw(_("You do not have access to that tenant."),
                     frappe.PermissionError)
    return tenant


def require_landlord_access(landlord, user=None):
    allowed = allowed_buildings(user)
    if allowed is None:
        return landlord
    if not frappe.db.exists("Head Lease", {
            "landlord": landlord, "building": ["in", sorted(allowed)]}):
        frappe.throw(_("You do not have access to that landlord."),
                     frappe.PermissionError)
    return landlord


def scoped_filters(filters=None, field="building", user=None):
    """Add the current user's explicit building boundary to query filters."""
    out = dict(filters or {})
    allowed = allowed_buildings(user)
    if allowed is not None:
        out[field] = ["in", sorted(allowed)]
    return out


def _query(doctype, field, user=None):
    user = user or frappe.session.user
    allowed = allowed_buildings(user)
    if allowed is None:
        return ""
    if not allowed:
        return "1=0"
    names = ", ".join(frappe.db.escape(a) for a in sorted(allowed))
    return f"`tab{doctype}`.`{field}` in ({names})"


def building_query(user=None):
    return _query("Building", "name", user)


def unit_query(user=None):
    return _query("Unit", "building", user)


def document_register_query(user=None):
    return _query("Document Register", "building", user)


def document_archive_query(user=None):
    return _query("Document Archive", "building", user)


def tenancy_query(user=None):
    return _query("Tenancy Agreement", "building", user)


def head_lease_query(user=None):
    return _query("Head Lease", "building", user)


def amendment_query(user=None):
    user = user or frappe.session.user
    allowed = allowed_buildings(user)
    if allowed is None:
        return ""
    if not allowed:
        return "1=0"
    names = ", ".join(frappe.db.escape(a) for a in sorted(allowed))
    return ("exists (select 1 from `tabTenancy Agreement` ta where "
            "`tabAgreement Amendment`.`agreement_type`='Tenancy Agreement' "
            "and ta.name=`tabAgreement Amendment`.`agreement` and "
            f"ta.building in ({names})) or exists (select 1 from `tabHead Lease` hl where "
            "`tabAgreement Amendment`.`agreement_type`='Head Lease' "
            "and hl.name=`tabAgreement Amendment`.`agreement` and "
            f"hl.building in ({names}))")


def supplier_query(user=None):
    user = user or frappe.session.user
    allowed = allowed_buildings(user)
    if allowed is None:
        return ""
    if not allowed:
        return "1=0"
    names = ", ".join(frappe.db.escape(a) for a in sorted(allowed))
    return ("ifnull(`tabSupplier`.`db_is_landlord`, 0)=0 or "
            "exists (select 1 from `tabBuilding` b where b.landlord=`tabSupplier`.name "
            f"and b.name in ({names}))")


def customer_query(user=None):
    user = user or frappe.session.user
    allowed = allowed_buildings(user)
    if allowed is None:
        return ""
    if not allowed:
        return "1=0"
    names = ", ".join(frappe.db.escape(a) for a in sorted(allowed))
    return ("ifnull(`tabCustomer`.`db_is_tenant`, 0)=0 or "
            "exists (select 1 from `tabTenancy Agreement` ta where "
            "ta.tenant=`tabCustomer`.name " + f"and ta.building in ({names}))")


def party_has_permission(doc, user=None, permission_type=None):
    """Restrict tenant/landlord detail access to buildings assigned to a user."""
    user = user or frappe.session.user
    allowed = allowed_buildings(user)
    if allowed is None:
        return None
    if doc.doctype == "Supplier" and doc.get("db_is_landlord"):
        return bool(frappe.db.exists("Building", {"landlord": doc.name,
                                                  "name": ["in", sorted(allowed)]}))
    if doc.doctype == "Customer" and doc.get("db_is_tenant"):
        return bool(frappe.db.exists("Tenancy Agreement", {"tenant": doc.name,
                                                            "building": ["in", sorted(allowed)]}))
    return None


def maintenance_query(user=None):
    return _query("Maintenance Request", "building", user)


def collection_query(user=None):
    return _query("Collection Case", "building", user)


def moveout_query(user=None):
    return _query("Move Out Case", "building", user)


def invoice_run_query(user=None):
    return _query("Invoice Run", "building", user)
