"""The books, read back.

Five screens sat in front of ERPNext's ledger for months without ever asking
it anything: chart of accounts, general ledger, journal entries, trial balance
and the single-account view. Each rendered the prototype's own invented
postings, so a live site showed a set of books that had never happened.

This module is the read side of that. It writes nothing. ERPNext owns the
ledger — every posting in it was made by a Sales Invoice, a Payment Entry or a
Journal Entry raised through a named workflow — and everything here is a query
over `GL Entry` and `Account`.

Two decisions worth stating.

    An account's code is its account number where it has one, and its name
    where it does not. ERPNext names accounts "Rental Income - DB"; the code
    column exists so a person can scan it, and an account without a number
    still has to appear rather than be silently dropped.

    The journal list is capped. A general ledger has no natural end, and a
    screen that tries to render all of it renders none of it. The cap is
    stated in the payload so the screen can say what it is showing rather
    than imply it is showing everything.
"""

import frappe
from frappe.utils import flt, getdate, today, add_months
from darkbrown.guards import guard, ACC, GM, MD

#: How many vouchers the journal screens carry. Past this the screen says so.
VOUCHER_CAP = 400

#: How far back the ledger reads by default.
DEFAULT_MONTHS = 12

#: Which side an account class sits on when it is behaving normally.
NORMAL = {"Asset": "Dr", "Expense": "Dr",
          "Liability": "Cr", "Equity": "Cr", "Income": "Cr"}

#: The prototype called them Sales/Purchase/Payment/Journal. ERPNext calls the
#: same events by their voucher type. Mapping here keeps the screen's filter
#: labels stable rather than showing raw doctype names.
VOUCHER_LABEL = {
    "Sales Invoice": "Sales",
    "Purchase Invoice": "Purchase",
    "Payment Entry": "Payment",
    "Journal Entry": "Journal",
    "Stock Entry": "Stock",
}


def _company():
    settings = frappe.get_single("DBR Settings")
    return (getattr(settings, "default_company", None)
            or frappe.db.get_value("Company", {}, "name"))


def _code(row):
    """A short handle for the account, stable enough to key on."""
    return (row.get("account_number")
            or (row.get("account_name") or row.get("name") or "").strip()
            or row.get("name"))


def _accounts(company=None):
    """Every posting account on the company, in code order."""
    filters = {"is_group": 0}
    if company:
        filters["company"] = company
    rows = frappe.get_all(
        "Account",
        filters=filters,
        fields=["name", "account_name", "account_number", "root_type",
                "account_type"],
        order_by="account_number asc, account_name asc",
        limit=2000)
    out = []
    for r in rows:
        cls = r.root_type or "Asset"
        out.append({
            "code": _code(r),
            "name": r.account_name or r.name,
            "cls": cls,
            "nat": NORMAL.get(cls, "Dr"),
            "acc": r.name,
            "type": r.account_type or "",
        })
    return out


def _window(frm=None, to=None):
    to = getdate(to) if to else getdate(today())
    frm = getdate(frm) if frm else getdate(add_months(to, -DEFAULT_MONTHS))
    return str(frm), str(to)


# ------------------------------------------------------------------- reading

def _gl(company, frm, to, accounts=None, limit=20000):
    filters = {"is_cancelled": 0, "posting_date": ["between", [frm, to]]}
    if company:
        filters["company"] = company
    if accounts:
        filters["account"] = ["in", accounts]
    return frappe.get_all(
        "GL Entry",
        filters=filters,
        fields=["posting_date", "account", "debit", "credit", "voucher_type",
                "voucher_no", "remarks", "party", "against", "owner"],
        order_by="posting_date desc, creation desc",
        limit=limit)


def _short_user(user):
    if not user or user == "Administrator":
        return "System"
    full = frappe.db.get_value("User", user, "full_name") or user
    bits = full.split()
    return bits[0] + (" " + bits[-1][0] + "." if len(bits) > 1 else "")


@frappe.whitelist()
def books(frm=None, to=None):
    """Chart of accounts plus the journals behind it, in one round trip.

    The five ledger screens all read the same two things, so they fetch them
    once between them rather than five times. Shapes match what those screens
    already render: the account is a four-slot row, the voucher carries its
    lines as [code, debit, credit].
    """
    guard(MD, GM, ACC)
    company = _company()
    frm, to = _window(frm, to)

    accounts = _accounts(company)
    by_account = {a["acc"]: a for a in accounts}
    entries = _gl(company, frm, to)

    vouchers = {}
    order = []
    for e in entries:
        key = (e.voucher_type, e.voucher_no)
        v = vouchers.get(key)
        if v is None:
            if len(order) >= VOUCHER_CAP:
                continue
            v = vouchers[key] = {
                "id": e.voucher_no,
                "d": str(e.posting_date),
                "ty": VOUCHER_LABEL.get(e.voucher_type, e.voucher_type or "—"),
                "vt": e.voucher_type,
                "desc": (e.remarks or e.against or e.voucher_no or "—")[:160],
                "ref": e.voucher_no,
                "by": _short_user(e.owner),
                "lines": [],
                "tot": 0.0,
            }
            order.append(key)
        a = by_account.get(e.account)
        code = a["code"] if a else (e.account or "—")
        v["lines"].append([code, flt(e.debit), flt(e.credit)])
        v["tot"] += flt(e.debit)

    jrn = [vouchers[k] for k in order]

    # Balances are computed over the whole window, not over the capped
    # voucher list, or an account's balance would move when the cap moved.
    bal = {}
    for e in entries:
        a = by_account.get(e.account)
        code = a["code"] if a else (e.account or "—")
        b = bal.setdefault(code, {"dr": 0.0, "cr": 0.0})
        b["dr"] += flt(e.debit)
        b["cr"] += flt(e.credit)

    coa = []
    for a in accounts:
        b = bal.get(a["code"], {"dr": 0.0, "cr": 0.0})
        # An account that has never been posted to is still part of the chart,
        # but the ledger and trial balance screens only show movement.
        coa.append([a["code"], a["name"], a["cls"], a["nat"],
                    round(b["dr"], 2), round(b["cr"], 2)])

    groups = {"bank": [], "receivable": [], "payable": [], "cash": [],
              "deposits": []}
    for a in accounts:
        t = (a["type"] or "").lower()
        if t == "bank":
            groups["bank"].append(a["code"])
        elif t == "cash":
            groups["cash"].append(a["code"])
        elif t == "receivable":
            groups["receivable"].append(a["code"])
        elif t == "payable":
            groups["payable"].append(a["code"])
        if "deposit" in (a["name"] or "").lower() and a["cls"] == "Liability":
            groups["deposits"].append(a["code"])

    return {
        "coa": coa,
        "jrn": jrn,
        "groups": groups,
        "from": frm,
        "to": to,
        "capped": len(order) >= VOUCHER_CAP,
        "cap": VOUCHER_CAP,
        "company": company,
        "accounts": len(accounts),
    }


@frappe.whitelist()
def voucher(voucher_type=None, voucher_no=None):
    """One posting with its lines, for the journal detail view."""
    guard(MD, GM, ACC)
    if not voucher_no:
        frappe.throw("No voucher was named.")
    company = _company()
    filters = {"voucher_no": voucher_no, "is_cancelled": 0}
    if voucher_type:
        filters["voucher_type"] = voucher_type
    if company:
        filters["company"] = company
    rows = frappe.get_all(
        "GL Entry", filters=filters,
        fields=["posting_date", "account", "debit", "credit", "voucher_type",
                "voucher_no", "remarks", "party", "against", "owner",
                "cost_center"],
        order_by="debit desc, credit desc", limit=200)
    if not rows:
        frappe.throw("That posting is not in the ledger, or it was cancelled.")
    accounts = {a["acc"]: a for a in _accounts(company)}
    first = rows[0]
    return {
        "id": first.voucher_no,
        "d": str(first.posting_date),
        "ty": VOUCHER_LABEL.get(first.voucher_type, first.voucher_type),
        "vt": first.voucher_type,
        "ref": first.voucher_no,
        "desc": (first.remarks or first.against or "—")[:300],
        "by": _short_user(first.owner),
        "party": first.party or "",
        "cc": first.cost_center or "",
        "lines": [[(accounts.get(r.account) or {}).get("code", r.account),
                   (accounts.get(r.account) or {}).get("name", r.account),
                   flt(r.debit), flt(r.credit)] for r in rows],
        "tot": round(sum(flt(r.debit) for r in rows), 2),
    }


@frappe.whitelist()
def trial_balance(as_on=None):
    """Every account with movement up to a date, and whether it balances.

    Kept separate from `books` because the trial balance is asked as at a
    date rather than over a window, and running it off a windowed read would
    quietly drop opening positions.
    """
    guard(MD, GM, ACC)
    company = _company()
    as_on = str(getdate(as_on) if as_on else getdate(today()))
    accounts = _accounts(company)
    by_account = {a["acc"]: a for a in accounts}

    filters = {"is_cancelled": 0, "posting_date": ["<=", as_on]}
    if company:
        filters["company"] = company
    sums = frappe.get_all(
        "GL Entry", filters=filters, fields=["account", "sum(debit) as dr",
                                             "sum(credit) as cr"],
        group_by="account", limit=2000)

    rows, tot_dr, tot_cr = [], 0.0, 0.0
    for s in sums:
        a = by_account.get(s.account)
        if not a:
            continue
        dr, cr = flt(s.dr), flt(s.cr)
        if not dr and not cr:
            continue
        tot_dr += dr
        tot_cr += cr
        rows.append([a["code"], a["name"], a["cls"], a["nat"],
                     round(dr, 2), round(cr, 2)])
    rows.sort(key=lambda r: str(r[0]))
    return {"rows": rows, "dr": round(tot_dr, 2), "cr": round(tot_cr, 2),
            "balanced": abs(tot_dr - tot_cr) < 0.01, "as_on": as_on,
            "company": company}
