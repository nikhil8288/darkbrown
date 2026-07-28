"""Row-level scoping.

The General Manager sees the buildings assigned to them; everyone else with
read permission sees the portfolio. Assignment uses Frappe's own User
Permission mechanism so there is one place to change who sees what.
"""

import frappe


def _scoped(user):
    """Buildings this user has been restricted to, if any."""
    return [p.for_value for p in frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Building"},
        fields=["for_value"])]


def building_query(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    roles = set(frappe.get_roles(user))
    if "Managing Director" in roles or "System Manager" in roles:
        return ""
    allowed = _scoped(user)
    if not allowed:
        return ""
    names = ", ".join(frappe.db.escape(a) for a in allowed)
    return f"`tabBuilding`.name in ({names})"


def unit_query(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    roles = set(frappe.get_roles(user))
    if "Managing Director" in roles or "System Manager" in roles:
        return ""
    allowed = _scoped(user)
    if not allowed:
        return ""
    names = ", ".join(frappe.db.escape(a) for a in allowed)
    return f"`tabUnit`.building in ({names})"
