import frappe
from frappe import _

# Page-level configuration
no_cache = 1


def get_context(context):
    """Server-side guard. The MD dashboard is read-only and restricted to the
    Managing Director role. System Manager / Administrator can also view it for
    setup and debugging.
    """
    user = frappe.session.user

    if user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/md-dashboard"
        raise frappe.Redirect

    roles = set(frappe.get_roles(user))
    allowed = {"Managing Director", "System Manager", "Administrator"}

    if not (roles & allowed):
        frappe.throw(
            _("You do not have permission to view the Managing Director dashboard."),
            frappe.PermissionError,
        )

    # Full-width, no standard web header/footer chrome — this is an app surface.
    context.no_header = 1
    context.no_breadcrumbs = 1
    context.title = "Managing Director"

    # Expose a couple of safe values to the template if ever needed later.
    context.current_user = user
    context.is_md = "Managing Director" in roles

    return context
