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
from frappe.utils import (flt, date_diff, get_datetime, getdate,
                          now_datetime, today)
from darkbrown.guards import guard, ACC, MD


def _payload(payload):
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload or {}


# ------------------------------------------------------------ declarations

@frappe.whitelist()
def declare_balances(payload):
    """One declaration row per account. Returns the new opening total."""
    guard(MD, ACC)
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
    guard(MD, ACC)
    p = _payload(payload)
    raw_end = getdate(p.get("period_end") or _week_end())
    if raw_end.weekday() != 3:
        frappe.throw("A weekly close must end on a Thursday.")
    if raw_end > getdate(_week_end()):
        frappe.throw("A future week cannot be closed.")
    period_end = str(raw_end)
    status = p.get("status") or "In Progress"
    if status not in ("In Progress", "Closed"):
        frappe.throw("A weekly close can only be In Progress or Closed.")
    name = frappe.db.get_value("Weekly Closing", {"period_end": period_end})
    doc = frappe.get_doc("Weekly Closing", name) if name else frappe.get_doc(
        {"doctype": "Weekly Closing", "period_end": period_end})
    if name and doc.status == "Closed":
        return {"name": doc.name, "status": doc.status,
                "period_end": f"{getdate(doc.period_end):%d %b}",
                "discrepancies": doc.discrepancies or 0}

    start = frappe.utils.add_days(period_end, -6)
    checks = _checks(start, period_end)
    manual_keys = {c["k"] for c in checks if c["kind"] == "manual"}
    confirmed = p.get("manual_confirmed") or []
    if not isinstance(confirmed, (list, tuple)):
        frappe.throw("Manual confirmations must be a list.")
    confirmed = set(confirmed)
    if confirmed - manual_keys:
        frappe.throw("The close contains an unknown manual confirmation.")

    for check in checks:
        if check["kind"] == "manual":
            check["ok"] = 1 if check["k"] in confirmed else 0
            check["detail"] = ("Confirmed by " + frappe.session.user
                               if check["ok"] else "Not confirmed")

    open_checks = [c for c in checks if not c["ok"]]
    unconfirmed = [c["label"] for c in open_checks if c["kind"] == "manual"]
    notes = (p.get("notes") or "").strip()
    if unconfirmed:
        audit_note = "Not confirmed: " + "; ".join(unconfirmed)
        notes = (notes + " · " + audit_note).strip(" ·")

    doc.status = status
    doc.assigned_to = frappe.session.user
    doc.discrepancies = len(open_checks)
    doc.notes = notes or None
    doc.check_snapshot = frappe.as_json({
        "period_start": str(start), "period_end": period_end,
        "closed_by": frappe.session.user, "checks": checks,
    })
    if doc.status == "Closed" and not doc.closed_on:
        doc.closed_on = frappe.utils.now()
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

    imports = frappe.db.count(
        "Bank Statement Import",
        {"from_date": ["<=", end], "to_date": [">=", start]})
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
    guard(MD, ACC)
    end = _week_end(period_end)
    start = frappe.utils.add_days(end, -6)

    name = frappe.db.get_value("Weekly Closing", {"period_end": end})
    current = None
    if name:
        d = frappe.get_doc("Weekly Closing", name)
        recorded_checks = []
        if d.check_snapshot:
            try:
                snapshot = frappe.parse_json(d.check_snapshot) or {}
                if isinstance(snapshot, dict) and isinstance(snapshot.get("checks"), list):
                    recorded_checks = snapshot["checks"]
            except (TypeError, ValueError):
                # Older or manually repaired records may not contain a usable
                # snapshot.  The screen can still fall back to live checks.
                recorded_checks = []
        current = {
            "id": d.name, "st": d.status,
            "discrepancies": d.discrepancies or 0,
            "notes": d.notes or "",
            "checks": recorded_checks,
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
    guard(MD, ACC)
    p = _payload(payload)
    lines = p.get("lines") or []
    if not lines:
        frappe.throw("The statement has no lines.")
    if len(lines) > 5000:
        frappe.throw("A statement import is limited to 5,000 lines.")

    bank_account = p.get("bank_account")
    if not bank_account or not frappe.db.exists("Bank Account", bank_account):
        frappe.throw("Choose a valid company Bank Account.")
    if not p.get("from_date") or not p.get("to_date"):
        frappe.throw("The statement needs a period from and to date.")
    period_from, period_to = (getdate(p.get("from_date")),
                              getdate(p.get("to_date")))
    if period_from > period_to:
        frappe.throw("The statement period ends before it starts.")

    normalized, seen = [], set()
    for index, ln in enumerate(lines, 1):
        amount = flt(ln.get("amount"))
        direction = (ln.get("direction") or "").title()
        raw_date = ln.get("date")
        try:
            txn_date = getdate(raw_date) if raw_date else None
        except (TypeError, ValueError):
            txn_date = None
        if direction not in ("Credit", "Debit") or not txn_date or amount <= 0:
            frappe.throw(
                "Statement line {0} needs a valid date, positive amount, "
                "and Credit or Debit direction.".format(index))
        if txn_date < period_from or txn_date > period_to:
            frappe.throw("Statement line {0} is outside the import period.".format(
                index))
        key = (str(txn_date), (ln.get("ref") or "").strip(), amount, direction)
        if key in seen:
            frappe.throw("Statement line {0} is duplicated in this import.".format(
                index))
        seen.add(key)
        normalized.append({
            "date": str(txn_date), "ref": key[1],
            "narrative": (ln.get("narrative") or "").strip(),
            "amount": amount, "direction": direction,
        })

    prior_imports = frappe.get_all(
        "Bank Statement Import", filters={"bank_account": bank_account},
        pluck="name")
    if prior_imports:
        prior_lines = frappe.get_all(
            "Bank Statement Line", filters={"parent": ["in", prior_imports]},
            fields=["txn_date", "bank_ref", "amount", "direction"])
        prior_keys = {(str(r.txn_date), (r.bank_ref or "").strip(),
                       flt(r.amount), r.direction) for r in prior_lines}
        duplicate = next((key for key in seen if key in prior_keys), None)
        if duplicate:
            frappe.throw(
                "This bank line was already imported for {0}: {1}, {2}, {3}."
                .format(bank_account, duplicate[0], duplicate[1] or "no ref",
                        duplicate[2]))

    used = {"Deposit Batch": _already_matched("Deposit Batch"),
            "Cheque": _already_matched("Cheque"),
            "Head Lease Payment": _already_matched("Head Lease Payment")}

    def take(kind, sql, args):
        candidates = [name for name, in frappe.db.sql(sql, args)
                      if name not in used[kind]]
        # Amount/date proximity is not identity when two records fit.  An
        # ambiguous line stays visible for a human instead of whichever row
        # the database happened to return first being called a match.
        if len(candidates) != 1:
            return None
        used[kind].add(candidates[0])
        return candidates[0]

    doc = frappe.get_doc({
        "doctype": "Bank Statement Import",
        "bank_account": bank_account,
        "from_date": str(period_from),
        "to_date": str(period_to),
        "source": p.get("source") or "pasted",
        "status": "Posted",
    })

    for ln in normalized:
        amt, d, direction = ln["amount"], ln["date"], ln["direction"]
        status, mtype, mref = "Unmatched", None, None
        if direction == "Credit":
            mref = take("Deposit Batch", """
                select name from `tabDeposit Batch`
                where bank_account = %s
                  and status in ('Deposited', 'Reconciled')
                  and abs(total_amount - %s) <= %s
                  and abs(datediff(deposit_date, %s)) <= %s
                order by abs(datediff(deposit_date, %s))""",
                (bank_account, amt, MATCH_TOL, d, MATCH_DAYS, d))
            mtype = "Deposit Batch" if mref else None
            if not mref:
                mref = take("Cheque", """
                    select name from `tabCheque`
                    where direction = 'Incoming'
                      and bank_account = %s
                      and (deposit_batch is null or deposit_batch = '')
                      and status in ('Deposited', 'Cleared')
                      and abs(amount - %s) <= %s
                      and abs(datediff(coalesce(presented_on, cheque_date), %s)) <= %s
                    order by abs(datediff(coalesce(presented_on, cheque_date), %s))""",
                    (bank_account, amt, MATCH_TOL, d, MATCH_DAYS, d))
                mtype = "Cheque" if mref else None
        else:
            mref = take("Head Lease Payment", """
                select hp.name from `tabHead Lease Payment` hp
                inner join `tabCheque` c on c.name = hp.cheque
                where hp.status = 'Cleared'
                  and c.bank_account = %s
                  and abs(hp.amount - %s) <= %s
                  and abs(datediff(coalesce(c.cleared_on, c.presented_on,
                                             hp.due_date), %s)) <= %s
                order by abs(datediff(coalesce(c.cleared_on, c.presented_on,
                                                hp.due_date), %s))""",
                (bank_account, amt, MATCH_TOL, d, MATCH_DAYS, d))
            mtype = "Head Lease Payment" if mref else None
        if mref:
            status = "Matched"
        doc.append("lines", {
            "txn_date": d, "bank_ref": ln["ref"],
            "narrative": ln["narrative"], "amount": amt,
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
    # Whole riyals. This used to divide by a thousand on the way out, so the
    # panel's own label said QAR and showed thousandths of one.
    return {"imports": 1, "weeks": weeks, "items": open_rows[0],
            "value": round(flt(open_rows[1]), 2),
            "aged": int(open_rows[2] or 0)}


# --------------------------------------------------- classification workbench

#: What a bank line can be, and what that means for the cost base.
#:
#: `operating` decides whether the line belongs in the operating outflow the
#: reserve floor is computed on. An owner drawing is an equity movement, not a
#: cost, and leaving it in overstates the denominator — which is the whole
#: reason this screen exists.
#:
#: `equity` marks the two that move the owners' current account. Tagging one
#: does not post it. The posting account is Q21 and the Owners module is
#: Stage 2I; writing an equity entry against an account nobody has agreed
#: would be a guess in the ledger, which is the one place a guess must not go.
#: The tag is durable and the posting can be run against it later.
CLASSIFICATIONS = {
    "Tenant collection": {"operating": True},
    "Landlord payment": {"operating": True},
    "Payroll": {"operating": True},
    "Utility payment": {"operating": True},
    "Maintenance cost": {"operating": True},
    "Petty cash top-up": {"operating": True},
    "Bank charge": {"operating": True},
    "Other operating cost": {"operating": True},
    "Shareholder drawing": {"operating": False, "equity": True},
    "Shareholder injection": {"operating": False, "equity": True},
    "Transfer between own accounts": {"operating": False},
    "Unattributed cash": {"operating": True},
}

#: Narrative fragments that suggest what a line is. A suggestion is a prompt to
#: look, never an answer — nothing is applied without a person choosing it.
HINTS = (
    ("shareholder drawing", ("kunhabdu", "khayaz", "raziya")),
    ("Bank charge", ("charge", "fee", "commission", "returned item")),
    ("Unattributed cash", ("atm", "cash wdl", "cash withdrawal")),
    ("Petty cash top-up", ("petty",)),
    ("Payroll", ("salary", "payroll", "wps")),
)


def _suggest(line):
    narrative = (line.get("narrative") or "").lower()
    for label, needles in HINTS:
        for n in needles:
            if n in narrative:
                # The shareholder hint is a name match, and a name match is
                # the weakest evidence there is — two people can share one.
                if label == "shareholder drawing":
                    return ("Shareholder drawing",
                            "payer name matches a shareholder — verify")
                return (label, f"narrative contains '{n}'")
    return (None, "")


@frappe.whitelist()
def reconciliation(limit=200):
    """Everything the reconciliation screen shows, read from the imports.

    The import path has been live for months and nothing ever read it back,
    so the screen showed a fixed 148/139/9 next to real portfolio figures.
    This is the read side: what was imported, what matched, what is still
    open, and what has been classified out of the cost base.

    No reserve floor is computed here. The denominator is Q11 and the
    posting account is Q21; a floor built on either would be a number with
    a decimal point and no meaning.
    """
    guard(MD, ACC)
    limit = int(limit or 200)

    imports = frappe.get_all(
        "Bank Statement Import",
        fields=["name", "bank_account", "from_date", "to_date", "status",
                "total_lines", "matched", "unmatched", "creation"],
        order_by="creation desc", limit=20)
    if not imports:
        return {"imports": 0, "lines": [], "classified": [], "flagged": [],
                "summary": {}, "runs": []}

    has_classification = frappe.get_meta(
        "Bank Statement Line").has_field("classification")

    fields = ["name", "parent", "txn_date", "bank_ref", "narrative", "amount",
              "direction", "status", "matched_type", "matched_ref"]
    if has_classification:
        fields += ["classification", "classify_note", "classified_by",
                   "classified_on"]

    rows = frappe.get_all(
        "Bank Statement Line", filters={"parenttype": "Bank Statement Import"},
        fields=fields, order_by="txn_date desc", limit=5000)

    total = len(rows)
    matched = sum(1 for r in rows if r.status == "Matched")
    classified, flagged = [], []
    drawings = 0.0
    operating_out = 0.0

    for r in rows:
        cls = r.get("classification") if has_classification else None
        amount = flt(r.amount)
        debit = r.direction == "Debit"
        if cls:
            rule = CLASSIFICATIONS.get(cls, {})
            if rule.get("equity"):
                drawings += amount
            elif debit and rule.get("operating"):
                operating_out += amount
            classified.append({
                "id": r.name, "ref": r.bank_ref or "—",
                "d": str(r.txn_date), "amt": amount, "dir": r.direction,
                "nar": r.narrative or "—", "cls": cls,
                "note": r.get("classify_note") or "",
                "by": r.get("classified_by") or "",
                "equity": bool(rule.get("equity")),
            })
            continue
        if r.status in ("Matched", "Excluded"):
            if debit:
                operating_out += amount
            continue
        suggestion, why = _suggest(r)
        row = {
            "id": r.name, "ref": r.bank_ref or "—", "d": str(r.txn_date),
            "amt": amount, "dir": r.direction, "nar": r.narrative or "—",
            "age": date_diff(today(), r.txn_date) if r.txn_date else 0,
            "suggest": suggestion, "why": why,
            "flag": why or "no record matched on amount and date",
            "import": r.parent,
        }
        flagged.append(row)
        if debit:
            operating_out += amount

    flagged.sort(key=lambda r: -r["age"])
    classified.sort(key=lambda r: r["d"], reverse=True)

    return {
        "imports": len(imports),
        "runs": [{"id": i.name, "bank": i.bank_account,
                  "from": str(i.from_date or ""), "to": str(i.to_date or ""),
                  "lines": i.total_lines, "matched": i.matched,
                  "unmatched": i.unmatched, "st": i.status,
                  "when": str(i.creation)[:16]} for i in imports],
        "flagged": flagged[:limit],
        "classified": classified[:limit],
        "options": sorted(CLASSIFICATIONS.keys()),
        "deployed": has_classification,
        "summary": {
            "lines": total,
            "matched": matched,
            "unmatched": len(flagged),
            "classified": len(classified),
            "value": round(sum(r["amt"] for r in flagged), 2),
            "aged": sum(1 for r in flagged if r["age"] > 5),
            "drawings": round(drawings, 2),
            "operating": round(operating_out, 2),
            "last": str(imports[0].creation)[:16],
        },
    }


@frappe.whitelist()
def classify_line(line, classification, note=None):
    """Tag one bank line with what it actually is.

    This writes a classification and nothing else. It does not post, does not
    clear a cheque and does not touch the owners' current account: an equity
    movement needs an agreed posting account (Q21) and Stage 2I behind it, and
    until both exist the honest thing to record is the classification itself,
    which the posting run can then be driven from.
    """
    guard(MD, ACC)
    if classification not in CLASSIFICATIONS:
        frappe.throw(f"{classification} is not a classification this app knows.")
    meta = frappe.get_meta("Bank Statement Line")
    if not meta.has_field("classification"):
        frappe.throw("Classification fields are not on the site yet — "
                     "run bench migrate.")

    parent = frappe.db.get_value("Bank Statement Line", line, "parent")
    if not parent:
        frappe.throw("That statement line is not on any import.")
    doc = frappe.get_doc("Bank Statement Import", parent)
    row = next((l for l in doc.lines if l.name == line), None)
    if not row:
        frappe.throw("That statement line is not on any import.")

    rule = CLASSIFICATIONS[classification]
    row.classification = classification
    row.classify_note = (note or "").strip() or None
    row.classified_by = frappe.session.user
    row.classified_on = now_datetime()
    # A line that is not an operating movement is out of the cost base, and
    # the status has to say so or the next reader has to know the rule.
    if not rule.get("operating"):
        row.status = "Excluded"
    elif row.status == "Unmatched":
        row.status = "Classified"

    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()
    return {"line": line, "classification": classification,
            "status": row.status, "equity": bool(rule.get("equity")),
            "import": parent}
