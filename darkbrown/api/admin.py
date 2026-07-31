"""Data tools, driven from the application rather than a shell.

Purging and reseeding is a thing the owner does, not a thing a developer does
on his behalf, so it belongs on a screen with a button on it. These endpoints
sit behind the Data screen at #/data.

A rebuild takes minutes, which is longer than a web request should live. So
the work is handed to a background worker and the screen polls for the log
rather than waiting on the response. The log is kept in the cache under one
key; starting a new run clears it.
"""

import contextlib
import io

import frappe
from frappe import _

LOG_KEY = "darkbrown:demo:log"
STATE_KEY = "darkbrown:demo:state"
ACTIONS = ("purge", "seed", "verify", "rebuild")


# ------------------------------------------------------------------ guarding

def _guard():
    """Reserved. Wiping the portfolio is not a delegated action."""
    roles = set(frappe.get_roles())
    if not ({"System Manager", "Managing Director"} & roles):
        frappe.throw(_("Only the Managing Director may use the data tools."),
                     frappe.PermissionError)


# -------------------------------------------------------------------- log io

def _cache():
    return frappe.cache()


def _reset_log():
    _cache().set_value(LOG_KEY, "")
    _cache().set_value(STATE_KEY, "running")


def _append(text):
    if not text:
        return
    current = _cache().get_value(LOG_KEY) or ""
    _cache().set_value(LOG_KEY, (current + text)[-60000:])


def _finish(state):
    _cache().set_value(STATE_KEY, state)


# ------------------------------------------------------------------ endpoints

@frappe.whitelist()
def preview():
    """Count what is on the site now. Writes nothing, returns immediately."""
    _guard()
    from darkbrown.demo import purge as purge_mod
    counts = purge_mod.preview()
    return {"counts": counts,
            "total": sum(counts.values()) if counts else 0,
            "confirm": purge_mod.CONFIRM}


@frappe.whitelist()
def start(action, confirm=None, wide=0):
    """Hand a long job to a background worker."""
    _guard()
    if action not in ACTIONS:
        frappe.throw(_("{0} is not a data action.").format(action))

    if action in ("purge", "rebuild"):
        from darkbrown.demo import purge as purge_mod
        if confirm != purge_mod.CONFIRM:
            frappe.throw(_("Type the confirmation phrase exactly to go "
                           "ahead: {0}").format(purge_mod.CONFIRM))

    if (_cache().get_value(STATE_KEY) or "") == "running":
        frappe.throw(_("A data job is already running. Wait for it to "
                       "finish."))

    _reset_log()
    frappe.enqueue("darkbrown.api.admin.execute", queue="long", timeout=3600,
                   action=action, confirm=confirm, wide=int(wide or 0),
                   user=frappe.session.user)
    return {"started": action}


@frappe.whitelist()
def progress():
    """What the worker has printed so far, and whether it is still going."""
    _guard()
    return {"state": _cache().get_value(STATE_KEY) or "idle",
            "log": _cache().get_value(LOG_KEY) or ""}


@frappe.whitelist()
def clear():
    _guard()
    _cache().set_value(LOG_KEY, "")
    _cache().set_value(STATE_KEY, "idle")
    return {"cleared": True}


# ----------------------------------------------------------------- the worker

def execute(action, confirm=None, wide=0, user=None):
    """Runs in the background. Everything the demo scripts print is captured
    line by line so the screen can show it as it happens."""
    # Deliberately not the user who pressed the button. Seeding writes
    # Payment Entries and Sales Invoices, and whether the MD happens to hold
    # the ERPNext accounting roles is beside the point for a data tool. The
    # gate is on start(), which is where it belongs.
    frappe.set_user("Administrator")

    from darkbrown.demo import run as run_mod

    buf = _Tee()
    try:
        with contextlib.redirect_stdout(buf):
            if action == "purge":
                run_mod.purge(confirm=confirm, wide=bool(wide))
            elif action == "seed":
                run_mod.seed()
            elif action == "verify":
                run_mod.verify()
            elif action == "rebuild":
                run_mod.rebuild(confirm=confirm, wide=bool(wide))
        _append("\n\nDone.\n")
        _finish("done")
    except Exception:
        _append("\n\nSTOPPED\n" + frappe.get_traceback())
        _finish("failed")
        frappe.log_error(frappe.get_traceback(), "darkbrown data tools")
    finally:
        frappe.db.commit()


class _Tee(io.TextIOBase):
    """Pushes each write straight into the cache so the screen can follow
    along rather than waiting for the whole run to end."""

    def write(self, text):
        _append(text)
        return len(text)

    def flush(self):
        pass
