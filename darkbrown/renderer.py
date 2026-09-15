"""Serves the prototype as the application.

Not a www template. The prototype's CSS contains sequences Jinja reads as
comment delimiters ("{#kpis"), so rendering it through the template engine
would mangle it. This renderer hands the file over untouched and injects the
boot payload by replacing a single marker.
"""

import json
import os

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

ROUTES = ("darkbrown", "db")

APP_ROLES = ("Managing Director", "General Manager", "Accounts",
             "Documentation", "Maintenance", "System Manager")

_SHELL = os.path.join(os.path.dirname(__file__), "shell", "index.html")


class DarkBrownApp(BaseRenderer):
    def can_render(self):
        return self.path in ROUTES

    def render(self):
        if frappe.session.user == "Guest":
            frappe.local.flags.redirect_location = (
                f"/login?redirect-to=/{self.path}")
            raise frappe.Redirect

        roles = set(frappe.get_roles(frappe.session.user))
        if not roles & set(APP_ROLES):
            frappe.throw("You do not have access to this application.",
                         frappe.PermissionError)

        return self.build_response(_html())


def _html():
    with open(_SHELL, encoding="utf-8") as fh:
        html = fh.read()
    return html.replace("<!--DB_BOOT-->", _boot(), 1)


def _boot():
    from darkbrown.api import app as api

    payload = {
        "seed": api.seed(),
        "role": api.role_code(),
        "user": frappe.db.get_value("User", frappe.session.user, "full_name"),
        "csrf": frappe.sessions.get_csrf_token(),
    }
    return (
        "<script>\n"
        f"window.DB_SEED={_script_json(payload['seed'])};\n"
        f"window.DB_ROLE={_script_json(payload['role'])};\n"
        f"window.DB_USER={_script_json(payload['user'])};\n"
        f"window.DB_CSRF={_script_json(payload['csrf'])};\n"
        "window.DB_OCR_ENABLED=false;\n"
        "</script>"
    )


def _script_json(value):
    """Serialize JSON that cannot terminate its containing script element.

    JSON string escaping alone does not treat ``</script>`` specially because
    the HTML parser runs before JavaScript. Escaping HTML delimiters and the
    two JavaScript line separators keeps stored text data-only in this context.
    """
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))
