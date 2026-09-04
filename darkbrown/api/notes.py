"""The decision trail.

Until now there was none. The composer in the shell wrote into a hardcoded
map in the browser, so a note typed on a live site was accepted, acknowledged,
and gone on the next render — which is why the panel was made to say so rather
than keep pretending.

This stores them, and it does it on Frappe's own `Comment` rather than on a new
doctype. Three reasons. A note belongs to the record it is about, not to a
parallel table that has to be kept in step. Anything written here is visible in
the Desk timeline of that record, and anything written in the Desk shows up
here — one trail, not two. And `frappe.has_permission` on the referenced record
is then the whole access rule, so a note can never be more readable than the
thing it is attached to.

Roles are read off the session, never sent by the caller. The prototype had a
dropdown for it, which is fine in a demo and wrong here: nobody signs their own
note as the Managing Director.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from darkbrown.guards import guard, APP

#: What a note may be attached to. An allowlist rather than "any doctype",
#: because this endpoint takes a doctype name from the browser and
#: `has_permission` on an obscure system doctype is not a check anybody
#: reasoned about.
NOTABLE = (
    "Agreement Amendment",
    "Tenancy Agreement",
    "Head Lease",
    "Maintenance Request",
    "Security Deposit",
    "Invoice Run",
    "Collection Case",
    "Move Out Case",
    "Cheque",
    "Document Register",
    "Building",
    "Unit",
)

#: Frappe role -> the short label the shell shows on a note.
ROLE_LABEL = (
    ("Managing Director", "MD", "Managing Director"),
    ("General Manager", "GM", "General Manager"),
    ("Accounts", "ACC", "Accounts"),
    ("Documentation", "DOC", "Documentation"),
    ("Maintenance", "MNT", "Maintenance"),
)


def _ago(when):
    """How long ago, in words. Done here rather than with frappe.utils
    pretty_date, which is not importable on every build."""
    try:
        secs = (now_datetime() - get_datetime(when)).total_seconds()
    except Exception:
        return ""
    for cut, unit, div in ((60, "just now", 1), (3600, "minute", 60),
                           (86400, "hour", 3600), (2592000, "day", 86400)):
        if secs < cut:
            if div == 1:
                return unit
            n = int(secs // div) or 1
            return "%d %s%s ago" % (n, unit, "" if n == 1 else "s")
    return str(when)[:10]


def _check(doctype, name):
    """The record-level half of the rule. The role-level half is `guard` at
    the endpoint itself, where the scanner can see it - a guard buried in a
    helper reads as ungated, and an endpoint nobody can prove is gated is one
    nobody should trust."""
    if doctype not in NOTABLE:
        frappe.throw(_("Notes are not kept against {0}.").format(doctype))
    if not frappe.db.exists(doctype, name):
        frappe.throw(_("No {0} called {1}.").format(doctype, name))
    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw(
            _("You cannot read {0}, so you cannot read its notes.").format(name),
            frappe.PermissionError)


def _author(user):
    """Who wrote it, and in what capacity, resolved at read time.

    Read time rather than write time is deliberate: a note is signed by the
    role its author holds, and if that changes the trail should not claim they
    held the old one when they wrote it. The cost is one query per author,
    which is why the caller caches.
    """
    roles = set(frappe.get_roles(user))
    for role, short, label in ROLE_LABEL:
        if role in roles:
            return short, label
    return "", frappe.db.get_value("User", user, "full_name") or user


@frappe.whitelist()
def thread(doctype, name):
    """Every note on one record, oldest first — a trail reads forwards."""
    guard(*APP)
    _check(doctype, name)

    rows = frappe.get_all(
        "Comment",
        filters={"comment_type": "Comment", "reference_doctype": doctype,
                 "reference_name": name},
        fields=["name", "content", "owner", "creation"],
        order_by="creation asc", limit=200)

    seen, out = {}, []
    for r in rows:
        if r.owner not in seen:
            short, label = _author(r.owner)
            full = frappe.db.get_value("User", r.owner, "full_name") or r.owner
            seen[r.owner] = (short, label, full)
        short, label, full = seen[r.owner]
        out.append({
            "id": r.name,
            "by": full,
            "role": short or label,
            "when": str(r.creation)[:16],
            "ago": _ago(r.creation),
            "t": frappe.utils.strip_html(r.content or "").strip(),
            "mine": r.owner == frappe.session.user,
        })
    return {"notes": out, "count": len(out),
            "doctype": doctype, "name": name}


@frappe.whitelist()
def add(doctype, name, text):
    """Write one note. Returns the thread, so the caller does not have to
    fetch again to show what it just wrote."""
    guard(*APP)
    _check(doctype, name)
    text = (text or "").strip()
    if not text:
        frappe.throw(_("An empty note is not a note."))
    if len(text) > 5000:
        frappe.throw(_("That note is too long — keep it under 5,000 characters."))

    # add_comment is the same call the Desk timeline makes, so a note written
    # here is indistinguishable from one written there.
    frappe.get_doc(doctype, name).add_comment("Comment", text)
    frappe.db.commit()
    return thread(doctype, name)


def record(doctype, name, text):
    """Internal: file a note without the permission dance.

    Used by `approvals.decide`, where the caller has already been checked
    against a stricter rule than reading the record. It never raises — a
    decision that went through must not be reported as failed because its
    note could not be written — but it does log, because a silently missing
    audit line is the thing this module exists to stop.
    """
    if not text or doctype not in NOTABLE:
        return None
    try:
        frappe.get_doc(doctype, name).add_comment("Comment", text)
        return True
    except Exception:
        frappe.log_error(frappe.get_traceback(),
                         "darkbrown: note not recorded on %s %s" % (doctype, name))
        return False
