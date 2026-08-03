"""Petty cash: a float with a balance, not a list of receipts.

The difference matters. An expense log answers what was spent. A float answers
whether the money that should be in the box still is — and in a business where
the accounts sweep to near zero daily and cash leaves by ATM without a payee,
that second question is the one worth being able to answer.

So this records movements. Cash in, cash out, and the correction when a
physical count disagrees with the book. The balance is derived from those
movements and never stored, because a stored balance and a movement history
can disagree, and when they do there is no way to tell which one lied.

Two connections to work already done:

    Top-ups name the account they came from, which turns an anonymous ATM
    withdrawal into a classified one. That is a piece of Q24 — not all of it,
    since cash leaves the accounts for other reasons too, but a real piece.

    Spend is portfolio overhead (D79) and does not reach building margin, on
    the same reasoning as staff cost: allocating it across buildings on an
    invented key would make each building's margin a property of the rule
    rather than of its lease.
"""

import json

import frappe
from frappe.utils import add_months, flt, get_first_day, getdate, today


def _payload(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload or {}


def _signed(row):
    """Amounts are always stored positive; the movement decides the sign.

    An adjustment can go either way, so it carries its own direction. Assuming
    a sign here would mean a shortfall found in the box quietly increasing the
    book — the exact opposite of what the count discovered.
    """
    d = row.get("direction") if hasattr(row, "get") else row.direction
    amt = flt(row.get("amount") if hasattr(row, "get") else row.amount)
    if d == "Top-up":
        return amt
    if d == "Expense":
        return -amt
    if d == "Adjustment":
        eff = (row.get("adjustment_effect") if hasattr(row, "get")
               else row.adjustment_effect)
        return amt if eff == "Increase" else -amt
    return 0.0


# ---------------------------------------------------------------- balance

def float_balance(on=None):
    """Book balance as at a date. Not whitelisted — screens go through
    petty_cash_summary, which is guarded like everything else here."""
    on = getdate(on or today())
    rows = frappe.get_all(
        "Petty Cash Entry", filters={"entry_date": ["<=", on]},
        fields=["direction", "amount", "adjustment_effect"],
        ignore_permissions=True)
    total = 0.0
    for r in rows:
        total += _signed(r)
    return total


def monthly_spend_average(months=3, on=None):
    """Trailing average monthly spend, for the forward views.

    A one-off in March tells you nothing about next March, so the projection
    cannot use actuals. It uses this instead, and it is an average and says so
    — the runway keeps the actual dated movements and this does not go near it.
    """
    on = getdate(on or today())
    start = get_first_day(add_months(on, -int(months)))
    rows = frappe.get_all(
        "Petty Cash Entry",
        filters={"direction": "Expense",
                 "entry_date": ["between", [start, on]]},
        fields=["amount"], ignore_permissions=True)
    if not rows:
        return 0.0
    return sum(flt(r.amount) for r in rows) / float(months or 1)


def spend_between(start, end):
    """Actual spend in a window — what the bridge wants, since the bridge is
    a record of what happened and not a forecast."""
    rows = frappe.get_all(
        "Petty Cash Entry",
        filters={"direction": "Expense",
                 "entry_date": ["between", [getdate(start), getdate(end)]]},
        fields=["amount"], ignore_permissions=True)
    return sum(flt(r.amount) for r in rows)


# ------------------------------------------------------------------ reads

@frappe.whitelist()
def entries(limit=100, direction=None):
    """Movements newest first, each carrying the balance as it stood after it.

    The running balance is computed forward from the beginning rather than
    backward from now, so an entry back-dated into the middle of the history
    reshapes every balance after it, which is what actually happened.
    """
    filters = {}
    if direction:
        filters["direction"] = direction
    rows = frappe.get_all(
        "Petty Cash Entry", filters=filters,
        fields=["name", "entry_date", "direction", "amount", "category",
                "description", "funded_from", "reference", "reason",
                "adjustment_effect", "notes"],
        order_by="entry_date asc, creation asc", ignore_permissions=True)

    running = 0.0
    for r in rows:
        running += _signed(r)
        r["balance"] = running

    rows.reverse()
    out = []
    for r in rows[:int(limit or 100)]:
        out.append({
            "id": r.name, "date": str(r.entry_date), "dir": r.direction,
            "amount": flt(r.amount), "cat": r.category or "",
            "what": r.description or "", "from": r.funded_from or "",
            "ref": r.reference or "", "reason": r.reason or "",
            "effect": r.adjustment_effect or "",
            "balance": r["balance"],
        })
    return out


@frappe.whitelist()
def petty_cash_summary(on=None):
    on = getdate(on or today())
    month_start = get_first_day(on)
    return {
        "balance": float_balance(on),
        "thisMonth": spend_between(month_start, on),
        "average": monthly_spend_average(3, on),
        "lastTopUp": frappe.db.get_value(
            "Petty Cash Entry", {"direction": "Top-up"}, "entry_date",
            order_by="entry_date desc"),
    }


# ----------------------------------------------------------------- writes

@frappe.whitelist()
def record_entry(payload):
    p = _payload(payload)
    doc = frappe.new_doc("Petty Cash Entry")
    doc.entry_date = getdate(p.get("date") or today())
    doc.direction = p.get("dir") or "Expense"
    doc.amount = flt(p.get("amount"))
    doc.category = p.get("cat")
    doc.description = p.get("what")
    doc.funded_from = p.get("from")
    doc.reference = p.get("ref")
    doc.reason = p.get("reason")
    doc.notes = p.get("notes")
    doc.insert()
    frappe.db.commit()
    return {"id": doc.name, "balance": float_balance()}


@frappe.whitelist()
def record_count(counted, on=None, reason=None):
    """A physical count of the box.

    If it agrees with the book, nothing is written — a count that changes
    nothing is not a movement. If it does not, the difference is recorded as
    an adjustment with the explanation attached, so the history shows that a
    count happened and what it found. Writing the book silently down to the
    box would leave no trace that anything went missing.
    """
    on = getdate(on or today())
    book = float_balance(on)
    diff = round(flt(counted) - book, 2)
    if abs(diff) < 0.005:
        return {"agreed": True, "book": book, "counted": flt(counted),
                "diff": 0.0}
    if not reason:
        frappe.throw(
            "The count does not agree with the book by {0}. An adjustment "
            "needs a reason — recording it without one would hide the only "
            "evidence that something is missing.".format(diff))

    doc = frappe.new_doc("Petty Cash Entry")
    doc.entry_date = on
    doc.direction = "Adjustment"
    doc.amount = abs(diff)
    doc.adjustment_effect = "Increase" if diff > 0 else "Decrease"
    doc.reason = reason
    doc.reference = "Count on {0}".format(on)
    doc.notes = ("Book stood at {0}, counted {1}."
                 .format(round(book, 2), flt(counted)))
    doc.insert()
    frappe.db.commit()
    return {"agreed": False, "book": book, "counted": flt(counted),
            "diff": diff, "id": doc.name, "balance": float_balance()}
