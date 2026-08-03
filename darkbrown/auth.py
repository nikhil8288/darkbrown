import frappe

# The shell is the application. Every business role lands on it.
#
# This file used to send the Managing Director to /managing_director_dashboard
# and everyone else to a desk workspace — /app/gm-overview, /app/dbr-finance,
# /app/legal-docs, /app/maintenance-desk. That was V1's routing. The MD page
# has been removed, the workspaces are desk pages behind the app the shell
# replaced, and one of the branches named a role ("Legal and Documentation")
# that V2 does not define, so it could never have matched. Signing in put
# people somewhere other than the product.
APP_HOME = "/darkbrown"

APP_ROLES = ("Managing Director", "General Manager", "Accounts",
             "Documentation", "Maintenance")


def on_session_creation(login_manager):
    """Runs on every successful login.

    Frappe sends every System User to /app after login and only consults the
    Role 'Home Page' field for Website Users, which is why business roles kept
    landing on the desk and reading "Not Permitted". Administrator is left
    alone — the desk is where the site gets administered.
    """
    user = login_manager.user
    if user in ("Administrator", "Guest"):
        return

    if set(frappe.get_roles(user)) & set(APP_ROLES):
        frappe.local.response["home_page"] = APP_HOME
