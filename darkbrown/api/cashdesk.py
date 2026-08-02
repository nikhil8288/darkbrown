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
    if doc.status == "Closed" and not doc.closed_on:
        doc.closed_on = frappe.utils.now()
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


def _week_end(on=None):
    """The Thursday of the week we are closing.

    The close is a Thursday evening job, so the period runs Friday to
    Thursday. On a Thursday it is today; otherwise it is the Thursday just
    gone, because a close is done on what has happened, not on what has not.
    """
    d = getdate(on or today())
    # Monday is 0, so Thursday is 3
    back = (d.weekday() - 3) % 7
    return frappe.utils.add_days(d, -back)


def _checks(start, end):
    """The checklist, computed rather than pre-ticked.

    Every item the records can answer is answered by them and cannot be
    ticked by hand. The rest are honest manual confirmations: somebody says
    they did it, and their saying so is the record. The two kinds are marked
    differently on screen, because a green tick nobody earned is worse than
    an open item.
    """
    out = []

    def derived(key, label, count, detail_ok, detail_bad, route=None):
        out.append({"k": key, "label": label, "kind": "derived",
                    "ok": 1 if not count else 0, "count": count,
                    "detail": detail_ok if not count else detail_bad,
                    "go": route})

    imports = frappe.db.count("Bank Statement Import",
                              {"to_date": [">=", start]})
    out.append({"k": "stmt", "label": "Bank statement imported",
                "kind": "derived", "ok": 1 if imports else 0,
                "count": imports,
                "detail": (f"{imports} import covering this week" if imports
                           else "No statement has been imported for this week"),
                "go": "#/recon"})

    unmatched = frappe.db.count("Bank Statement Line", {"status": "Unmatched"})
    derived("unmatched", "Reconciliation exceptions cleared", unmatched,
            "Nothing unmatched", f"{unmatched} line(s) still unmatched", "#/recon")

    undeposited = frappe.db.count("Deposit Batch",
                                  {"status": "Draft",
                                   "deposit_date": ["<=", end]})
    derived("batches", "Every batch made this week is at the bank", undeposited,
            "Nothing waiting to go in",
            f"{undeposited} batch(es) prepared but not banked", "#/batches")

    held = frappe.db.count("Cheque",
                           {"direction": "Incoming", "status": "Received",
                            "cheque_date": ["<=", end]})
    derived("cheques", "Matured cheques presented", held,
            "No matured cheque is sitting in the office",
            f"{held} cheque(s) past their date and still on hand", "#/cheques")

    stale = frappe.db.sql("""
        select count(*) from `tabCollection Case`
        where status in ('Open', 'Contacted', 'Promised', 'Broken Promise')
          and (modified < %s or modified is null)
    """, (start,))[0][0]
    derived("cases", "Arrears cases reviewed", stale,
            "Every open case was touched this week",
            f"{stale} open case(s) not touched since the last close", "#/cases")

    # Nothing in the ledger answers these, so they stay somebody's word.
    for key, label in (("landlord", "Landlord cheque schedule confirmed"),
                       ("maint", "Maintenance costs posted"),
                       ("util", "Utility invoices captured")):
        out.append({"k": key, "label": label, "kind": "manual",
                    "ok": 0, "count": 0, "detail": "Confirmed by hand",
                    "go": None})
    return out


@frappe.whitelist()
def closing(period_end=None):
    """The current close, what it is waiting on, and the ones before it."""
    end = _week_end(period_end)
    start = frappe.utils.add_days(end, -6)

    name = frappe.db.get_value("Weekly Closing", {"period_end": end})
    current = None
    if name:
        d = frappe.get_doc("Weekly Closing", name)
        current = {
            "id": d.name, "st": d.status,
            "discrepancies": d.discrepancies or 0,
            "notes": d.notes or "",
            "assigned": (frappe.db.get_value("User", d.assigned_to, "full_name")
                         or d.assigned_to) if d.assigned_to else "—",
            "closed_on": (frappe.utils.format_datetime(d.closed_on, "d MMM HH:mm")
                          if d.closed_on else None),
        }

    history = []
    for r in frappe.get_all("Weekly Closing",
                            fields=["name", "period_end", "status",
                                    "discrepancies", "closed_on", "assigned_to"],
                            order_by="period_end desc", limit=10):
        if r.name == name:
            continue
        history.append({
            "id": r.name,
            "period": f"{getdate(r.period_end):%d %b %y}",
            "st": r.status,
            "discrepancies": r.discrepancies or 0,
            "closed_on": (frappe.utils.format_datetime(r.closed_on, "d MMM HH:mm")
                          if r.closed_on else "—"),
            "by": (frappe.db.get_value("User", r.assigned_to, "full_name")
                   or r.assigned_to) if r.assigned_to else "—",
        })

    checks = _checks(start, end)
    return {
        "period_end": str(end),
        "period": f"{getdate(start):%d %b} to {getdate(end):%d %b %y}",
        "current": current,
        "history": history,
        "checks": checks,
        "open": sum(1 for c in checks if not c["ok"]),
    }


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
