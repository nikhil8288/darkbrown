import frappe

MD_HOME = "/managing_director_dashboard"


def on_session_creation(login_manager):
    """Runs on every successful login.

    For the Managing Director we override Frappe's default landing page.
    (Frappe sends every System User to /app after login, and the Role
    'Home Page' field is only consulted for Website Users — which is why
    the MD kept landing on /app and getting 'Not Permitted'.)
    """
    user = login_manager.user
    if user in ("Administrator", "Guest"):
        return

    roles = frappe.get_roles(user)

    if "Managing Director" in roles:
        frappe.local.response["home_page"] = MD_HOME
        return

    # role -> workspace landing (priority order for multi-role users)
    for role, route in (("General Manager", "/app/gm-overview"),
                        ("Accounts", "/app/dbr-finance"),
                        ("Legal and Documentation", "/app/legal-docs"),
                        ("Maintenance", "/app/maintenance-desk")):
        if role in roles:
            frappe.local.response["home_page"] = route
            return
