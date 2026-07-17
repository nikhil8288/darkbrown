import frappe

# Never cache: this page is role-gated and Frappe's website cache is
# shared across sessions.
no_cache = 1

ALLOWED_ROLES = {"Legal and Documentation", "System Manager", "Managing Director"}


def get_context(context):
    # Not logged in -> send to the branded login page, then bounce back here
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/doc-intake"
        raise frappe.Redirect

    if not ALLOWED_ROLES & set(frappe.get_roles(frappe.session.user)):
        frappe.throw(
            "You are not permitted to access this page.",
            frappe.PermissionError,
        )

    context.user_full_name = frappe.db.get_value(
        "User", frappe.session.user, "full_name"
    )
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
