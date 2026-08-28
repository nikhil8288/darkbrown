"""The V1 Managing Director dashboard, retired.

This page was a second MD surface. It read `api.md_dashboard.get_all`,
`api.charts.*` and `api.attention.*`; the shell reads none of those — it is
driven by one `api.app.refresh` payload. Two surfaces computing the same
portfolio down two different code paths agree only by accident, and the moment
real records landed they were going to disagree in front of the one person who
could least afford to be shown two sets of figures.

`auth.py` has sent every business role to /darkbrown since V2, and its comment
already said this page "has been removed". It had not been: the route still
resolved, so a bookmark, a browser-restored tab or an old link still opened it.
This makes that true. Anyone arriving here is sent to the same MD command
centre everyone else lands on.

The Python behind it is left in place deliberately. `api.attention` is live —
`api.app._attention` calls `get_attention` for the seed payload — and
`api.md_dashboard` and `api.charts` are read-only and harmless unlinked.
Deleting them is a separate decision from closing the second door.
"""

import frappe

# Role-gated, and now a redirect: never let the website cache stand in for it.
no_cache = 1

APP_HOME = "/darkbrown"


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = (
            f"/login?redirect-to={APP_HOME}")
        raise frappe.Redirect

    # Everyone, MD included. The old page threw a 403 at non-MD users; there is
    # nothing here to protect now, and the shell does its own role gating.
    frappe.local.flags.redirect_location = f"{APP_HOME}#/dash"
    raise frappe.Redirect
