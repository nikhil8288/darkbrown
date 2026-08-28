"""The three statements, read off the ledger.

The trial balance already reads ERPNext honestly. The statements the accountant
actually signs did not exist: the shell carried a "Profit and loss" and a
"Balance sheet" card, but both sat below the `if(c.state==='ok') return
trialLive(...)` line in ROUTES.trial, so they were reachable only in the
prototype and were built from twenty hardcoded account codes. Live, there was a
trial balance and nothing else. There was no cash flow anywhere; the only thing
by that name is the MD dashboard's twelve-month forward projection, which is a
forecast, not a statement.

This module is the read side of all three. Like `api.accounting` it writes
nothing. ERPNext owns the ledger; everything here is a query over `GL Entry` and
`Account`.

Four decisions worth stating, because each one is the difference between a
statement that is correct and a statement that merely renders.

    The balance sheet carries unclosed earnings. Assets equal liabilities plus
    equity only once the profit that has not yet been swept into retained
    earnings is on the equity side. Taking income less expense cumulatively to
    the as-at date gives exactly that unclosed portion, because a Period Closing
    Voucher has already moved closed years into equity. Without this line the
    statement does not balance, and a balance sheet that does not balance is not
    a balance sheet.

    The profit and loss excludes Period Closing Vouchers. They are not trading;
    they are the sweep. Leaving them in double-counts every closed period that
    the window happens to span.

    The cash flow is direct, not indirect. ERPNext's own Cash Flow report is
    indirect and reads a Cash Flow Mapper that this site has never configured,
    so it would return a shape with nothing in it. This one classifies actual
    movement on the Cash and Bank accounts by the counterpart legs of the
    voucher that moved them. It needs no setup, it derives purely from the GL,
    and it reconciles: opening plus the three buckets equals closing, and the
    payload says so rather than asking anyone to trust it.

    Every bucket shows its accounts. A cash flow that shows three totals cannot
    be argued with, which is a fault rather than a virtue. The classification
    below is a reasonable default and not a rule of nature — deposits held and
    shareholder current accounts are the ones most likely to be wanted
    elsewhere — so each bucket carries the accounts that made it up and the
    person reading can see where a number came from and say move it.
"""

import frappe
from frappe.utils import flt, getdate, today, add_months, add_days
from darkbrown.guards import guard, ACC, GM, MD

#: Ceiling on the accounts pulled for the tree. The chart is a few hundred.
ACCOUNT_CAP = 2000

#: Ceiling on the vouchers the cash flow will walk in one window.
VOUCHER_CAP = 20000

#: How many names go into one `in` filter. Long IN lists are what turns a
#: report into a database incident.
CHUNK = 300

#: Which side an account class sits on when it is behaving normally. Matches
#: api.accounting.NORMAL deliberately — two modules disagreeing about the sign
#: of a liability is the kind of thing nobody notices until a statement prints.
NORMAL = {"Asset": "Dr", "Expense": "Dr",
          "Liability": "Cr", "Equity": "Cr", "Income": "Cr"}

#: The sweep. Trading statements leave it out; the balance sheet does not.
CLOSING_VOUCHER = "Period Closing Voucher"

#: Account types that mean cash for the purposes of the cash flow.
CASH_TYPES = ("Cash", "Bank")

#: Account types that make a movement investing rather than operating.
INVESTING_TYPES = ("Fixed Asset", "Accumulated Depreciation",
                   "Capital Work in Progress")


def _company():
    settings = frappe.get_single("DBR Settings")
    return (getattr(settings, "default_company", None)
            or frappe.db.get_value("Company", {}, "name"))


def _code(row):
    """A short handle for the account, stable enough to key on."""
    return (row.get("account_number")
            or (row.get("account_name") or row.get("name") or "").strip()
            or row.get("name"))


def _window(frm=None, to=None):
    """The reporting window. Defaults to the fiscal year to date where the
    site has fiscal years, and to twelve months back where it does not."""
    to = getdate(to) if to else getdate(today())
    if frm:
        return str(getdate(frm)), str(to)
    start = None
    try:
        from erpnext.accounts.utils import get_fiscal_year
        start = get_fiscal_year(to, as_dict=True).get("year_start_date")
    except Exception:
        start = None
    return str(getdate(start) if start else add_months(to, -12)), str(to)


# ----------------------------------------------------------------- the chart

def _tree(company=None):
    """Every account on the company, groups included, keyed by docname.

    The statements are hierarchical and the trial balance is not, which is why
    this does not reuse `api.accounting._accounts` — that one drops groups, and
    a profit and loss without its groups is a list rather than a statement.
    """
    filters = {}
    if company:
        filters["company"] = company
    rows = frappe.get_all(
        "Account",
        filters=filters,
        fields=["name", "account_name", "account_number", "root_type",
                "account_type", "is_group", "parent_account", "lft"],
        order_by="lft asc",
        limit=ACCOUNT_CAP)
    nodes = {}
    for r in rows:
        cls = r.root_type or "Asset"
        nodes[r.name] = {
            "acc": r.name,
            "code": _code(r),
            "label": r.account_name or r.name,
            "cls": cls,
            "nat": NORMAL.get(cls, "Dr"),
            "type": r.account_type or "",
            "group": bool(r.is_group),
            "parent": r.parent_account or None,
            "lft": r.lft or 0,
            "kids": [],
            "dr": 0.0,
            "cr": 0.0,
        }
    for n in nodes.values():
        p = nodes.get(n["parent"])
        if p is not None:
            p["kids"].append(n)
    for n in nodes.values():
        n["kids"].sort(key=lambda k: (k["lft"], str(k["code"])))
    return nodes


def _sums(company, frm=None, to=None, exclude_closing=False):
    """Debits and credits per account, either as at a date or over a window."""
    filters = {"is_cancelled": 0}
    if company:
        filters["company"] = company
    if frm:
        filters["posting_date"] = ["between", [frm, to]]
    else:
        filters["posting_date"] = ["<=", to]
    if exclude_closing:
        filters["voucher_type"] = ["!=", CLOSING_VOUCHER]
    rows = frappe.get_all(
        "GL Entry", filters=filters,
        fields=["account", "sum(debit) as dr", "sum(credit) as cr"],
        group_by="account", limit=ACCOUNT_CAP)
    return {r.account: (flt(r.dr), flt(r.cr)) for r in rows}


def _apply(nodes, sums):
    for acc, (dr, cr) in sums.items():
        n = nodes.get(acc)
        if n is not None:
            n["dr"] = dr
            n["cr"] = cr


def _rollup(node):
    """Total a subtree, in presentation sign, and cache it on the node."""
    total = _signed(node)
    for k in node["kids"]:
        total += _rollup(k)
    node["total"] = round(total, 2)
    return node["total"]


def _signed(node):
    """One account's own balance, positive when it behaves normally.

    An expense with a credit balance and an income with a debit balance are
    both real and both print negative, which is the point: a contra line that
    silently flipped sign would read as ordinary trading.
    """
    dr, cr = node["dr"], node["cr"]
    return (dr - cr) if node["nat"] == "Dr" else (cr - dr)


def _flatten(node, depth, out, drop_empty=True):
    """Depth-tagged rows for a screen that indents rather than nests."""
    if drop_empty and not node.get("total") and not node["kids"]:
        return
    if drop_empty and node["group"] and not node.get("total"):
        if not any(k.get("total") for k in _descendants(node)):
            return
    out.append({
        "code": node["code"],
        "label": node["label"],
        "cls": node["cls"],
        "type": node["type"],
        "acc": node["acc"],
        "depth": depth,
        "group": node["group"],
        "amount": node.get("total", 0.0),
    })
    for k in node["kids"]:
        _flatten(k, depth + 1, out, drop_empty)


def _descendants(node):
    for k in node["kids"]:
        yield k
        for g in _descendants(k):
            yield g


def _roots(nodes, root_type):
    """Top of each root_type. A chart can have more than one."""
    out = [n for n in nodes.values()
           if n["cls"] == root_type and (
               not n["parent"] or nodes.get(n["parent"], {}).get("cls")
               != root_type)]
    out.sort(key=lambda n: n["lft"])
    return out


def _section(nodes, root_type, label):
    roots = _roots(nodes, root_type)
    rows, total = [], 0.0
    for r in roots:
        _rollup(r)
        total += r["total"]
        _flatten(r, 0, rows)
    return {"key": root_type.lower(), "label": label,
            "rows": rows, "total": round(total, 2)}


# --------------------------------------------------------- profit and loss

@frappe.whitelist()
def profit_and_loss(frm=None, to=None):
    """Trading over a window: income, expense and what is left.

    Period Closing Vouchers are excluded. They move a closed year's profit into
    equity and are not trading, so a window spanning one would otherwise count
    that year twice.
    """
    guard(MD, GM, ACC)
    company = _company()
    frm, to = _window(frm, to)
    nodes = _tree(company)
    _apply(nodes, _sums(company, frm, to, exclude_closing=True))

    income = _section(nodes, "Income", "Income")
    expense = _section(nodes, "Expense", "Expenses")
    net = round(income["total"] - expense["total"], 2)
    margin = round(net / income["total"] * 100, 1) if income["total"] else None
    return {"sections": [income, expense],
            "income": income["total"], "expense": expense["total"],
            "net": net, "margin": margin,
            "frm": frm, "to": to, "company": company}


# ------------------------------------------------------------ balance sheet

@frappe.whitelist()
def balance_sheet(as_on=None):
    """Position as at a date, including the profit that has not been closed.

    The unclosed line is not decoration. Every posting balances, so assets plus
    expenses equal liabilities plus equity plus income; rearranged, assets equal
    liabilities plus equity plus income less expense. That last term is the
    profit still sitting in the trading accounts because no Period Closing
    Voucher has swept it. Omit it and the statement is out by exactly the
    year's result.
    """
    guard(MD, GM, ACC)
    company = _company()
    as_on = str(getdate(as_on) if as_on else getdate(today()))
    nodes = _tree(company)
    _apply(nodes, _sums(company, None, as_on))

    assets = _section(nodes, "Asset", "Assets")
    liabilities = _section(nodes, "Liability", "Liabilities")
    equity = _section(nodes, "Equity", "Equity")

    # Cumulative, and over everything including the sweep: what is left in the
    # trading accounts after closing is by definition the unclosed part.
    income = sum(_rollup(r) for r in _roots(nodes, "Income"))
    expense = sum(_rollup(r) for r in _roots(nodes, "Expense"))
    unclosed = round(income - expense, 2)

    equity["rows"].append({
        "code": "", "label": "Profit for the unclosed period",
        "cls": "Equity", "type": "", "acc": None,
        "depth": 0, "group": False, "amount": unclosed})
    equity["total"] = round(equity["total"] + unclosed, 2)

    left = assets["total"]
    right = round(liabilities["total"] + equity["total"], 2)
    return {"sections": [assets, liabilities, equity],
            "assets": left, "liabilities": liabilities["total"],
            "equity": equity["total"], "unclosed": unclosed,
            "difference": round(left - right, 2),
            "balanced": abs(left - right) < 0.01,
            "as_on": as_on, "company": company}


# ---------------------------------------------------------------- cash flow

def _bucket(node):
    """Which activity a counterpart account makes a cash movement.

    Deliberately shallow. Equity is financing, the capitalised asset types are
    investing, everything else is operating — which for a business that head-
    leases buildings and sublets units is very nearly all of it. The accounts
    behind each total travel with the payload so this can be argued with.
    """
    if node["type"] == "Equity" or node["cls"] == "Equity":
        return "financing"
    if node["type"] in INVESTING_TYPES:
        return "investing"
    return "operating"


def _cash_accounts(nodes):
    return {n["acc"]: n for n in nodes.values()
            if not n["group"] and n["type"] in CASH_TYPES}


def _chunked(seq):
    seq = list(seq)
    for i in range(0, len(seq), CHUNK):
        yield seq[i:i + CHUNK]


@frappe.whitelist()
def cash_flow(frm=None, to=None):
    """Where the cash actually went, by the direct method.

    For every voucher that touched a Cash or Bank account in the window, the
    net cash it moved is allocated across that voucher's other legs in
    proportion to their size, and each of those legs is classified. A transfer
    between two bank accounts has no other legs and nets to nothing, so it
    correctly disappears rather than inflating both sides.

    The reconciliation is the point of the whole thing: opening plus the three
    buckets equals closing, and closing is the same number the balance sheet
    prints for cash. If it ever does not, `reconciled` says so.
    """
    guard(MD, GM, ACC)
    company = _company()
    frm, to = _window(frm, to)
    nodes = _tree(company)
    cash = _cash_accounts(nodes)
    if not cash:
        return {"buckets": [], "opening": 0.0, "closing": 0.0, "net": 0.0,
                "reconciled": True, "difference": 0.0, "frm": frm, "to": to,
                "company": company, "accounts": [],
                "note": "No account on this company is typed Cash or Bank."}

    names = list(cash)

    def _cash_bal(upto, inclusive=True):
        op = "<=" if inclusive else "<"
        total = 0.0
        for chunk in _chunked(names):
            filters = {"is_cancelled": 0, "account": ["in", chunk],
                       "posting_date": [op, upto]}
            if company:
                filters["company"] = company
            rows = frappe.get_all(
                "GL Entry", filters=filters,
                fields=["sum(debit) as dr", "sum(credit) as cr"], limit=1)
            if rows:
                total += flt(rows[0].dr) - flt(rows[0].cr)
        return round(total, 2)

    opening = _cash_bal(add_days(getdate(frm), -1))
    closing = _cash_bal(getdate(to))

    # Which vouchers moved cash in the window.
    vouchers = set()
    for chunk in _chunked(names):
        filters = {"is_cancelled": 0, "account": ["in", chunk],
                   "posting_date": ["between", [frm, to]]}
        if company:
            filters["company"] = company
        for r in frappe.get_all(
                "GL Entry", filters=filters,
                fields=["voucher_type", "voucher_no"],
                group_by="voucher_type, voucher_no", limit=VOUCHER_CAP):
            vouchers.add((r.voucher_type, r.voucher_no))

    # Every leg of those vouchers, cash and not.
    legs = {}
    for chunk in _chunked({v[1] for v in vouchers}):
        filters = {"is_cancelled": 0, "voucher_no": ["in", chunk]}
        if company:
            filters["company"] = company
        for r in frappe.get_all(
                "GL Entry", filters=filters,
                fields=["voucher_type", "voucher_no", "account",
                        "debit", "credit"], limit=VOUCHER_CAP * 4):
            legs.setdefault((r.voucher_type, r.voucher_no), []).append(r)

    by_account, totals = {}, {"operating": 0.0, "investing": 0.0,
                              "financing": 0.0, "unallocated": 0.0}

    for key in vouchers:
        rows = legs.get(key) or []
        cash_net = sum(flt(r.debit) - flt(r.credit)
                       for r in rows if r.account in cash)
        if abs(cash_net) < 0.005:
            continue
        others = [r for r in rows if r.account not in cash]
        weights = [abs(flt(r.debit) - flt(r.credit)) for r in others]
        spread = sum(weights)
        if not others or spread < 0.005:
            totals["unallocated"] += cash_net
            continue
        for r, w in zip(others, weights):
            n = nodes.get(r.account)
            if n is None:
                totals["unallocated"] += cash_net * (w / spread)
                continue
            share = cash_net * (w / spread)
            b = _bucket(n)
            totals[b] += share
            slot = by_account.setdefault(
                (b, r.account),
                {"bucket": b, "code": n["code"], "label": n["label"],
                 "cls": n["cls"], "type": n["type"], "amount": 0.0})
            slot["amount"] += share

    buckets = []
    for key, label in (("operating", "Operating activities"),
                       ("investing", "Investing activities"),
                       ("financing", "Financing activities")):
        rows = [dict(v, amount=round(v["amount"], 2))
                for k, v in by_account.items() if k[0] == key
                and abs(v["amount"]) >= 0.005]
        rows.sort(key=lambda r: -abs(r["amount"]))
        buckets.append({"key": key, "label": label, "rows": rows,
                        "total": round(totals[key], 2)})

    net = round(sum(totals.values()), 2)
    difference = round(opening + net - closing, 2)
    return {"buckets": buckets,
            "opening": opening, "closing": closing, "net": net,
            "unallocated": round(totals["unallocated"], 2),
            "difference": difference,
            "reconciled": abs(difference) < 0.01,
            "vouchers": len(vouchers),
            "accounts": sorted(n["label"] for n in cash.values()),
            "frm": frm, "to": to, "company": company}
