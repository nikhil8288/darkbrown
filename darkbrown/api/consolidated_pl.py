"""Read-only monthly building P&L and exact, paginated cell drilldowns."""
import datetime
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

from darkbrown.guards import guard, MD, GM, ACC
from darkbrown.api import statements
from darkbrown.api.accounts_home import _access, _window

COMPANY_ROW = "__company__"
CAP = 50000
COLUMNS = [
    ("income", "Revenue"), ("head_lease", "Head Lease Rent"),
    ("cos", "Cost of Sales"), ("gross", "Gross Profit"),
    ("staff", "Staff Cost"), ("operating", "Operating Expenses"),
    ("depreciation", "Depreciation & Amortisation"),
    ("bank", "Bank Charges"), ("other", "Other Expenses"),
    ("net", "Net Profit / Loss"),
]
DIRECT = tuple(k for k, _ in COLUMNS if k not in ("gross", "net"))
GROUP_COLUMNS = {"Cost of Sales": "cos", "Staff Cost": "staff",
    "Operating Expenses": "operating", "Depreciation and Amortisation": "depreciation",
    "Bank and Finance Charges": "bank", "Other": "other"}


def _column(node, nodes):
    if node["group"]:
        return None
    if node["cls"] == "Income":
        return "income"
    if node["cls"] != "Expense":
        return None
    if node["label"].rsplit(" - ", 1)[0] == "Head Lease Rent":
        return "head_lease"
    return GROUP_COLUMNS[statements._expense_group(node, nodes)]


def _finish(values):
    d = {k: round(flt(values.get(k)), 2) for k in DIRECT}
    d["gross"] = round(d["income"] - d["head_lease"] - d["cos"], 2)
    d["expense"] = round(sum(d[k] for k in DIRECT if k != "income"), 2)
    d["net"] = round(d["income"] - d["expense"], 2)
    return d


def _cost_centres(company):
    centres = frappe.get_all("Cost Center", filters={"company": company},
        fields=["name", "parent_cost_center"], limit_page_length=5001)
    buildings = frappe.get_all("Building", fields=["name", "cost_center"],
        order_by="name asc", limit_page_length=5001)
    if len(centres) > 5000 or len(buildings) > 5000:
        frappe.throw("The cost-centre register exceeds report capacity.")
    parents = {c.name: c.parent_cost_center for c in centres}
    direct, names = {}, []
    for b in buildings:
        if b.cost_center and b.cost_center not in parents:
            continue  # A building belonging to another reporting company.
        names.append(b.name)
        if b.cost_center:
            if b.cost_center in direct:
                frappe.throw("Two buildings share a cost centre; correct the building mapping.")
            direct[b.cost_center] = b.name
    owners = {}
    for name in parents:
        cur, seen = name, set()
        while cur and cur not in seen:
            if cur in direct:
                owners[name] = direct[cur]
                break
            seen.add(cur)
            cur = parents.get(cur)
    return owners, names


def _filters(company, frm, to):
    return {"company": company, "is_cancelled": 0,
        "posting_date": ["between", [frm, to]],
        "voucher_type": ["!=", statements.CLOSING_VOUCHER]}


def _month_names(frm, to):
    cur = getdate(frm).replace(day=1)
    while cur <= getdate(to):
        yield str(cur)[:7]
        cur = (cur.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)


@frappe.whitelist()
def report(start=None, end=None):
    guard(MD, GM, ACC)
    _access()
    frm, to = _window(start, end)
    company = statements._company()
    if not company:
        frappe.throw("Configure the reporting company.")
    nodes = statements._tree(company)
    owners, names = _cost_centres(company)
    rows = frappe.get_all("GL Entry", filters=_filters(company, frm, to),
        fields=["account", "cost_center", "posting_date", "sum(debit) as dr", "sum(credit) as cr"],
        group_by="account, cost_center, posting_date", limit_page_length=CAP + 1)
    if len(rows) > CAP:
        frappe.throw("Too many daily account groups; choose a shorter reporting range.")
    amounts = defaultdict(lambda: defaultdict(float))
    for row in rows:
        node = nodes.get(row.account)
        if node is None:
            frappe.throw("The ledger includes an account missing from the reporting chart.")
        col = _column(node, nodes)
        if col is None:
            continue
        building = owners.get(row.cost_center, COMPANY_ROW)
        value = flt(row.cr) - flt(row.dr) if col == "income" else flt(row.dr) - flt(row.cr)
        amounts[(str(row.posting_date)[:7], building)][col] += value
    months, all_totals = [], defaultdict(float)
    for month in _month_names(frm, to):
        packed, totals = [], defaultdict(float)
        for building in names + [COMPANY_ROW]:
            vals = _finish(amounts[(month, building)])
            packed.append({"building": building, "label": "Company / unassigned costs"
                           if building == COMPANY_ROW else building, **vals})
            for k in DIRECT:
                totals[k] += vals[k]
                all_totals[k] += vals[k]
        months.append({"month": month, "rows": packed, "total": _finish(totals)})
    total = _finish(all_totals)
    # Reconcile independent account sums, not another sum of this same grid.
    pl = statements.profit_and_loss(frm=frm, to=to)
    expected = {g["key"]: g["total"] for g in pl["groups"]}
    checks = [(total[k], pl[k]) for k in ("income", "expense", "gross", "net")]
    checks += [(total["head_lease"] + total["cos"], pl["cost_of_sales"])]
    checks += [(total[k], expected.get(g, 0)) for g, k in GROUP_COLUMNS.items() if k != "cos"]
    if any(abs(a - b) > 0.01 for a, b in checks):
        frappe.throw("The consolidated building totals do not reconcile to the P&L.")
    return {"company": company, "currency": frappe.db.get_value("Company", company, "default_currency"),
        "frm": frm, "to": to, "columns": [{"key": k, "label": l} for k, l in COLUMNS],
        "months": months, "total": total, "reconciled": True, "notes": pl.get("notes", [])}


def _selection(company, nodes, building, bucket, frm, to):
    owners, names = _cost_centres(company)
    if building not in names and building not in (COMPANY_ROW, "__all__"):
        frappe.throw("Choose a valid building.")
    if bucket not in dict(COLUMNS):
        frappe.throw("Choose a valid P&L column.")
    cols = (set(DIRECT) if bucket == "net" else {"income", "head_lease", "cos"}
            if bucket == "gross" else {bucket})
    accounts = {a: n for a, n in nodes.items() if _column(n, nodes) in cols}
    filters = _filters(company, frm, to)
    filters["account"] = ["in", list(accounts)]
    # not-in retains unassigned company cost centres; NULL is added explicitly.
    or_filters = None
    if building == COMPANY_ROW:
        if owners:
            or_filters = [["cost_center", "not in", list(owners)], ["cost_center", "is", "not set"]]
    elif building != "__all__":
        owned = [c for c, b in owners.items() if b == building]
        filters["cost_center"] = ["in", owned]
        if not owned:
            accounts = {}  # An unmapped building's zero cell must not read company costs.
    return accounts, filters, or_filters


@frappe.whitelist()
def cell(month, building, bucket, page=0):
    guard(MD, GM, ACC)
    _access()
    frm, to = _window(month, month)
    try:
        page = int(page)
    except (TypeError, ValueError):
        frappe.throw("Choose a valid ledger page.")
    if page < 0:
        frappe.throw("Choose a valid ledger page.")
    company = statements._company()
    if not company:
        frappe.throw("Configure the reporting company.")
    nodes = statements._tree(company)
    accounts, filters, ors = _selection(company, nodes, building, bucket, frm, to)
    groups = frappe.get_all("GL Entry", filters=filters, or_filters=ors,
        fields=["account", "sum(debit) as dr", "sum(credit) as cr", "count(name) as entries"],
        group_by="account", limit_page_length=statements.ACCOUNT_CAP + 1) if accounts else []
    if len(groups) > statements.ACCOUNT_CAP:
        frappe.throw("The account breakdown exceeds report capacity.")
    packed, total, entries = [], 0.0, 0
    for g in groups:
        node = accounts[g.account]
        amount = (flt(g.cr) - flt(g.dr)) if bucket in ("gross", "net") or node["cls"] == "Income" else flt(g.dr) - flt(g.cr)
        amount = round(amount, 2)
        total += amount
        entries += int(g.entries or 0)
        packed.append({"account": g.account, "label": node["label"], "amount": amount})
    rows = frappe.get_all("GL Entry", filters=filters, or_filters=ors,
        fields=["name", "account", "cost_center", "posting_date", "voucher_type", "voucher_no", "debit", "credit"],
        order_by="posting_date desc, creation desc, name desc", limit_start=page * 100,
        limit_page_length=101) if accounts else []
    return {"month": month, "frm": frm, "to": to, "building": building,
        "building_label": ("Company / unassigned costs" if building == COMPANY_ROW else
                           "All buildings + company costs" if building == "__all__" else building),
        "bucket": bucket, "label": dict(COLUMNS)[bucket], "total": round(total, 2),
        "accounts": sorted(packed, key=lambda a: a["label"]), "entries": entries,
        "rows": rows[:100], "page": page, "has_more": len(rows) > 100,
        "notes": statements.reporting_status(company)["notes"]}
