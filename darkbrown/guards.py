"""One place that decides who may call what.

Every whitelisted endpoint in this app writes or reads business records through
`ignore_permissions=True`, which tells Frappe to skip the DocType permission
tables entirely. Those tables are correct and carefully set — and they were
being bypassed on every call, so the only thing standing between a Maintenance
login and `finance.record_receipt` was that the screen did not draw the button.

This module puts the check back. It is deliberately a plain function call at the
top of each endpoint rather than a decorator: Frappe introspects the signature of
a whitelisted function to map form arguments onto parameters, and wrapping
changes what that introspection sees. A first line in the body cannot break that,
and it greps.

The role sets below are read off the DocType permission JSON. Where an endpoint
writes a record, its guard is the set of roles that DocType grants write or
create to. Where it only reads, the guard is the read set. Nothing here is
invented; if a guard looks wrong the DocType table is where the argument is.
"""

import frappe
from frappe import _

MD = "Managing Director"
GM = "General Manager"
ACC = "Accounts"
DOC = "Documentation"
MNT = "Maintenance"
SM = "System Manager"

#: Everyone who is allowed into the application at all. Matches
#: renderer.APP_ROLES; used for boot and for portfolio-wide counts that every
#: role's own screen already shows them.
APP = (MD, GM, ACC, DOC, MNT)


def guard(*roles):
    """Raise unless the caller holds one of `roles`.

    System Manager and Administrator always pass — they are the people who
    install and repair the site, and locking them out of an endpoint only means
    the repair happens somewhere less visible.

    Called with no roles at all this denies everyone but the two above, which
    is the right default for a mistake: a guard that fails closed is a bug
    report, a guard that fails open is an incident.
    """
    if frappe.session.user == "Administrator":
        return
    allowed = set(roles) | {SM}
    if not (set(frappe.get_roles(frappe.session.user)) & allowed):
        frappe.throw(
            _("You do not have permission to do that."),
            frappe.PermissionError)


def has_any(*roles):
    """Non-raising form, for deciding what to return rather than whether to."""
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles(frappe.session.user)) & (set(roles) | {SM}))
