"""Legacy Data API: count previews and cached job status only.

Only the audited stage0_check worker remains enabled. Legacy mutation and
unaudited check/gate actions are denied at both request and worker dispatch.
Complete migration inventory is available only through the private bench export.
"""

import contextlib
import io

import frappe
from frappe import _

LOG_KEY = "darkbrown:demo:log"
STATE_KEY = "darkbrown:demo:state"
WRITE_CONFIRM = "MODIFY DARKBROWN DATA"
ACTIONS = ("purge", "seed", "verify", "rebuild",
           # Historical action names are retained for explicit denial.
           "stage0_check", "stage0_run", "stage0_gate",
           "stage1_check", "stage1_run", "stage1_gate",
           "stage2_check", "stage2_run", "stage2_gate",
           "stage3_check", "stage3_run", "stage3_gate",
           # Reload replaces a stage's records from a corrected worksheet.
           # Each refuses once a later stage depends on what it would remove.
           "stage1_reload", "stage2_reload", "stage3_reload",
           "stage4_check", "stage4_run", "stage4_gate", "stage4_reload",
           "stage5_check", "stage5_run", "stage5_gate", "stage5_reload",
           "stage6_check", "stage6_run", "stage6_gate", "stage6_reload",
           "stage7_check", "stage7_run", "stage7_gate", "stage7_reload",
           "stage8_check", "stage8_run", "stage8_gate", "stage8_reload",
           "stage9_check", "stage9_run", "stage9_gate", "stage9_reload",
           "stage10_check", "stage10_run", "stage10_gate", "stage10_reload",
           "stage11_check", "stage11_run", "stage11_gate", "stage11_reload")


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
def residual_preview():
    """Count what `purge` cannot see. Writes nothing.

    purge is scoped by party flag and by Building.cost_center, so a record
    that lost its flag - or a cost centre whose Building is already gone -
    does not appear in preview() and the screen reports an empty site while
    the records are still there.
    """
    _guard()
    from darkbrown.demo import residuals
    out = residuals.preview()
    out["total"] = sum(out["counts"].values()) if out["counts"] else 0
    return out


@frappe.whitelist()
def residual_sweep(confirm=None):
    """Remove the residue. Refuses on a live ledger or a loaded portfolio."""
    _guard()
    frappe.throw(_("Legacy cleanup is retired. Use the private migration inventory and reviewed execution package."))
    from darkbrown.demo import residuals
    if confirm != residuals.CONFIRM:
        frappe.throw(_("Type the confirmation phrase exactly to go "
                       "ahead: {0}").format(residuals.CONFIRM))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = residuals.run(confirm=confirm)
    out["log"] = buf.getvalue()
    return out


@frappe.whitelist()
def start(action, confirm=None, wide=0):
    """Hand a long job to a background worker."""
    _guard()
    _require_read_only_action(action)
    if action not in ACTIONS:
        frappe.throw(_("{0} is not a data action.").format(action))

    if action in ("purge", "rebuild", "stage0_run"):
        from darkbrown.demo import purge as purge_mod
        if confirm != purge_mod.CONFIRM:
            frappe.throw(_("Type the confirmation phrase exactly to go "
                       "ahead: {0}").format(purge_mod.CONFIRM))

    writes_data = (action == "seed" or
                   (action.startswith("stage") and
                    action.endswith(("_run", "_reload")) and
                    action != "stage0_run"))
    if writes_data and confirm != WRITE_CONFIRM:
        frappe.throw(_("Type the confirmation phrase exactly to modify site "
                       "data: {0}").format(WRITE_CONFIRM))

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

def _require_read_only_action(action):
    # Audited call graph: stage_00_wipe.check only reads counts and links.
    # In particular stage8/9_check create Overhead via _resolve. A suffix is
    # not evidence that a job is read-only. No other legacy job is admitted.
    if action != "stage0_check":
        frappe.throw(_("This legacy action is disabled. Use the private migration inventory; only stage0_check remains supported."))

def execute(action, confirm=None, wide=0, user=None):
    """Run the one audited legacy inventory; never commit a data transaction."""
    _require_read_only_action(action)
    from darkbrown.load import stage_00_wipe
    original_user = frappe.session.user
    frappe.set_user("Administrator")
    try:
        with contextlib.redirect_stdout(_Tee()):
            stage_00_wipe.check(wide=int(wide or 1))
        _finish("done")
    except Exception:
        _append("Inventory failed; use the private migration inventory export.")
        _finish("failed")
        raise
    finally:
        frappe.db.rollback()
        frappe.set_user(original_user)


class _Tee(io.TextIOBase):
    """Pushes each write straight into the cache so the screen can follow
    along rather than waiting for the whole run to end."""

    def write(self, text):
        _append(text)
        return len(text)

    def flush(self):
        pass
