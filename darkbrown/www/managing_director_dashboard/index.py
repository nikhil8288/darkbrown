import frappe

# Never cache: this page is role-gated and Frappe's website cache is
# shared across sessions.
no_cache = 1


def get_context(context):
    # Not logged in -> send to the branded login page, then bounce back here
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = (
            "/login?redirect-to=/managing_director_dashboard"
        )
        raise frappe.Redirect

    # Logged in but not the MD -> hard 403
    if "Managing Director" not in frappe.get_roles(frappe.session.user):
        frappe.throw(
            "You are not permitted to access this page.",
            frappe.PermissionError,
        )

    context.user_full_name = frappe.db.get_value(
        "User", frappe.session.user, "full_name"
    )
    return context
