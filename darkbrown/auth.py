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

    if "Managing Director" in frappe.get_roles(user):
        frappe.local.response["home_page"] = MD_HOME
