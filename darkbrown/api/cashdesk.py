"""Cash desk: declared balances, the weekly close, and the minimal
statement import.

Three rules hold this module together:

    Matching is identification, not posting. The auto-matcher marks a bank
    line as recognised; it never clears a cheque and never creates a payment
    entry. Money moves only through the named workflows that already exist.

    A match the matcher is not sure of does not happen. Credits are tried
    against deposit batches first — slip-to-deposit is the architecture this
    business needs, since three quarters of inflows carry no payer name —
    then against deposited cheques. Debits are tried against scheduled
    head-lease payments. Everything else stays Unmatched, visibly.

    A declared balance is a fact with an author and a timestamp. It is the
    only cash position this system will ever show, because the bank balance
    itself sweeps to near zero daily and means nothing.
"""

import json

import frappe
from frappe.utils import flt, get_datetime, getdate, now_datetime, today


def _payload(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload or {}


# ------------------------------------------------------------ declarations

@frappe.whitelist()
def declare_balances(payload):
    """One declaration row per account. Returns the new opening total."""
    p = _payload(payload)
    rows = p.get("rows") or []
    if not rows:
        frappe.throw("No balances given.")
    made = []
    for r in rows:
        if r.get("balance") in (None, ""):
            continue
        doc = frappe.get_doc({
            "doctype": "Bank Balance Declaration",
            "bank_account": r.get("bank_account"),
            "balance": flt(r.get("balance")),
            "notes": p.get("notes"),
        })
        doc.insert()
        made.append(doc.name)
    if not made:
        frappe.throw("No balances given.")
    total = sum(flt(frappe.db.get_value(
        "Bank Balance Declaration", n, "balance")) for n in made)
    return {"declared": made, "total": total,
            "on": f"{now_datetime():%d %b %H:%M}"}


def latest_declarations():
    """The most recent declaration per account, and the age of the oldest —
    the runway is only as fresh as its stalest account."""
    rows = frappe.db.sql("""
        select d.bank_account, d.balance, d.declared_on
        from `tabBank Balance Declaration` d
        join (select bank_account, max(declared_on) mo
              from `tabBank Balance Declaration` group by bank_account) x
          on x.bank_account = d.bank_account and x.mo = d.declared_on
    """, as_dict=True)
    if not rows:
        return None
    oldest = min(get_datetime(r.declared_on) for r in rows)
    return {
        "total": sum(flt(r.balance) for r in rows),
        "accounts": [{"a": r.bank_account, "b": flt(r.balance),
                      "on": f"{get_datetime(r.declared_on):%d %b}"}
                     for r in rows],
        "declared_on": f"{oldest:%d %b %H:%M}",
        "stale_days": (now_datetime() - oldest).days,
    }


# ------------------------------------------------------------ weekly close

@frappe.whitelist()
def record_close(payload):
    """Upserts the close for a period end. Starting one sets it In Progress;
    completing it sets Closed and stamps the time."""
    p = _payload(payload)
    period_end = p.get("period_end") or today()
    name = frappe.db.get_value("Weekly Closing", {"period_end": period_end})
    doc = frappe.get_doc("Weekly Closing", name) if name else frappe.get_doc(
        {"doctype": "Weekly Closing", "period_end": period_end})
    doc.status = p.get("status") or "In Progress"
    if p.get("assigned_to"):
        doc.assigned_to = p["assigned_to"]
    if p.get("discrepancies") not in (None, ""):
        doc.discrepancies = int(p["discrepancies"])
    if p.get("notes"):
        doc.notes = p["notes"]
    doc.save() if name else doc.insert()
    return {"name": doc.name, "status": doc.status,
            "period_end": f"{getdate(doc.period_end):%d %b}",
            "discrepancies": doc.discrepancies or 0}


# --------------------------------------------------------- statement import

MATCH_TOL = 1.0       # QAR — amounts must agree to within one riyal
MATCH_DAYS = 5        # calendar days either side


def _already_matched(kind):
    return set(r[0] for r in frappe.db.sql("""
        select matched_ref from `tabBank Statement Line`
        where status = 'Matched' and matched_type = %s""", (kind,)))


@frappe.whitelist()
def import_statement(payload):
    """Creates the import with its lines and runs the conservative matcher.
    Nothing is posted; unmatched lines surface on the Command Centre."""
    p = _payload(payload)
    lines = p.get("lines") or []
    if not lines:
        frappe.throw("The statement has no lines.")

    used = {"Deposit Batch": _already_matched("Deposit Batch"),
            "Cheque": _already_matched("Cheque"),
            "Head Lease Payment": _already_matched("Head Lease Payment")}

    def take(kind, sql, args):
        for name, in frappe.db.sql(sql, args):
            if name not in used[kind]:
                used[kind].add(name)
                return name
        return None

    doc = frappe.get_doc({
        "doctype": "Bank Statement Import",
        "bank_account": p.get("bank_account"),
        "from_date": p.get("from_date"),
        "to_date": p.get("to_date"),
        "source": p.get("source") or "pasted",
        "status": "Posted",
    })

    for ln in lines:
        amt, d = flt(ln.get("amount")), ln.get("date")
        direction = (ln.get("direction") or "").title()
        if direction not in ("Credit", "Debit") or not d or not amt:
            continue
        status, mtype, mref = "Unmatched", None, None
        if direction == "Credit":
            mref = take("Deposit Batch", """
                select name from `tabDeposit Batch`
                where abs(total_amount - %s) <= %s
                  and abs(datediff(deposit_date, %s)) <= %s
                order by abs(datediff(deposit_date, %s))""",
                (amt, MATCH_TOL, d, MATCH_DAYS, d))
            mtype = "Deposit Batch" if mref else None
            if not mref:
                mref = take("Cheque", """
                    select name from `tabCheque`
                    where direction = 'Incoming'
                      and status in ('Deposited', 'Cleared')
                      and abs(amount - %s) <= %s
                      and abs(datediff(cheque_date, %s)) <= %s
                    order by abs(datediff(cheque_date, %s))""",
                    (amt, MATCH_TOL, d, MATCH_DAYS, d))
                mtype = "Cheque" if mref else None
        else:
            mref = take("Head Lease Payment", """
                select name from `tabHead Lease Payment`
                where abs(amount - %s) <= %s
                  and abs(datediff(due_date, %s)) <= %s
                order by abs(datediff(due_date, %s))""",
                (amt, MATCH_TOL, d, MATCH_DAYS, d))
            mtype = "Head Lease Payment" if mref else None
        if mref:
            status = "Matched"
        doc.append("lines", {
            "txn_date": d, "bank_ref": ln.get("ref"),
            "narrative": ln.get("narrative"), "amount": amt,
            "direction": direction, "status": status,
            "matched_type": mtype, "matched_ref": mref,
        })

    if not doc.lines:
        frappe.throw("No usable lines. Each needs a date, an amount and "
                     "a direction (Credit or Debit).")
    doc.insert()
    return {"name": doc.name, "total": doc.total_lines,
            "matched": doc.matched, "unmatched": doc.unmatched}


def unmatched_summary():
    """Twelve weeks of unmatched items for the Command Centre panel, or a
    marker that no import has ever run."""
    if not frappe.db.count("Bank Statement Import"):
        return {"imports": 0}
    weeks = []
    for w in range(11, -1, -1):
        a = frappe.utils.add_days(today(), -(w + 1) * 7 + 1)
        b = frappe.utils.add_days(today(), -w * 7)
        weeks.append({"n": frappe.db.sql("""
            select count(*) from `tabBank Statement Line`
            where status = 'Unmatched' and txn_date between %s and %s
        """, (a, b))[0][0]})
    open_rows = frappe.db.sql("""
        select count(*), ifnull(sum(amount), 0),
               sum(case when datediff(%s, txn_date) > 5 then 1 else 0 end)
        from `tabBank Statement Line` where status = 'Unmatched'
    """, (today(),))[0]
    return {"imports": 1, "weeks": weeks, "items": open_rows[0],
            "value": round(flt(open_rows[1]) / 1000.0, 1),
            "aged": int(open_rows[2] or 0)}
