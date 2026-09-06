"""The expense chart, and the one fact about each head that the rest of the
system reads off it: whether the cost belongs to a building or to the company.

Two things live here that used to live nowhere.

    The P&L groups. The statement was a flat list of every expense account
    under one "Expenses" heading, which is a ledger dump rather than a profit
    and loss. Rent is a cost of the units being sublet; an audit fee is not.
    Five groups in a fixed order - cost of sales, staff, operating, writedowns,
    and what the bank takes - give the statement a gross margin in the middle
    of it, which is the number this business actually runs on.

    The basis. Every expense head is either attributable to one building or it
    is not, and that is a property of the head, not a judgement made at the
    keyboard each time. Building AC maintenance is always a building's cost.
    An audit fee never is. Recording that here means the entry screen can stop
    asking, and the allocation in `utils.allocation` has something to key on
    that will not drift.

Nothing here posts. It creates accounts if they are missing and reports what
each one is; `api.expenses` writes and `utils.allocation` divides.
"""

import frappe

#: Cost attributable to a single building. Posts to that building's cost
#: centre and reaches its margin directly.
BUILDING = "Building"

#: Cost the company carries as a whole. Posts to the overhead cost centre and
#: reaches building margin only through the allocation.
COMMON = "Common"

#: The P&L groups, in the order they print. The tuple is the group name and
#: the label the statement shows above it.
GROUPS = [
    ("Cost of Sales", "Cost of sales"),
    ("Staff Cost", "Staff cost"),
    ("Operating Expenses", "Operating expenses"),
    ("Depreciation and Amortisation", "Depreciation and amortisation"),
    # Named "Bank and Finance Charges" and not "Bank Charges" because an
    # ERPNext account name is unique per company, and the accountant's chart
    # already has a leaf called Bank Charges. A group and a leaf with the same
    # name means the leaf silently resolves to the group, and a posting to a
    # group account is refused - after the entry screen has already accepted
    # it. The statement prints the label below, so nothing user-facing changes.
    ("Bank and Finance Charges", "Bank charges"),
]

GROUP_NAMES = [g for g, _ in GROUPS]

#: Where the group accounts hang. First one that exists on the company wins;
#: the root Expense group is the fallback.
EXPENSE_PARENTS = ("Expenses", "Indirect Expenses", "Direct Expenses")

#: The cost centre that carries every common cost. Deliberately one centre and
#: not "no cost centre": a posting with no cost centre cannot be found later,
#: and the allocation needs a single place to read the pool from.
OVERHEAD_COST_CENTER = "Overhead"

#: The chart. Account name, P&L group, basis.
#:
#: Built from the accountant's mapping workbook (Expense Till 310726). Where
#: the workbook named an existing account in column B that is the name used;
#: where it named a new head in column C, that. Four places needed a decision
#: the workbook could not make on its own, and each is marked below.
HEADS = [
    # ---------------------------------------------------------- cost of sales
    ("Head Lease Rent", "Cost of Sales", BUILDING),
    ("Building AC Maintenance", "Cost of Sales", BUILDING),
    ("Building Maintenance", "Cost of Sales", BUILDING),
    ("Cleaning Pest Control", "Cost of Sales", BUILDING),
    ("Commission on Sales", "Cost of Sales", BUILDING),
    ("Electricity Buildings", "Cost of Sales", BUILDING),
    ("Key Money", "Cost of Sales", BUILDING),
    ("Marketing Expenses", "Cost of Sales", BUILDING),
    ("Repairs & Maintenance Equipment", "Cost of Sales", BUILDING),
    ("Wifi & Mobile Buildings", "Cost of Sales", BUILDING),

    # ------------------------------------------------------------ staff cost
    ("Salary", "Staff Cost", COMMON),
    ("Bonus Staffs", "Staff Cost", COMMON),
    ("Staff Ticket", "Staff Cost", COMMON),
    ("Staff Transportation", "Staff Cost", COMMON),
    ("Visa & Immigration", "Staff Cost", COMMON),
    # Watchmen and hired labour sit on a building and stay on it.
    ("Salary Watchmen", "Staff Cost", BUILDING),
    ("Temporary Staff", "Staff Cost", BUILDING),

    # ----------------------------------------------------- operating expenses
    ("Audit Fees", "Operating Expenses", COMMON),
    ("Electricity Office", "Operating Expenses", COMMON),
    ("IT & Software", "Operating Expenses", COMMON),
    ("Legal Expenses", "Operating Expenses", COMMON),
    ("Office Rent", "Operating Expenses", COMMON),
    # Moved out of cost of sales: it is no longer attributed to one building,
    # and a cost spread across all of them is not a cost of sale.
    ("Other Maintenance", "Operating Expenses", COMMON),
    ("Repairs & Maintenance", "Operating Expenses", COMMON),
    ("Repairs & Maintenance Vehicle", "Operating Expenses", COMMON),
    # The workbook mapped this to Marketing Expenses, which is a building cost
    # of sale. One account cannot be both, so it keeps its own head. Rename it
    # to whatever it should be called; nothing reads the string but the chart.
    ("Sharaf Personal Expenses", "Operating Expenses", COMMON),
    ("Sponsor Fees", "Operating Expenses", COMMON),
    ("Travel Expenses", "Operating Expenses", COMMON),
    # Food and office expenses both land here, as agreed - one account, not two.
    ("Utility Expenses", "Operating Expenses", COMMON),
    ("Vehicle Fuel", "Operating Expenses", COMMON),
    ("Wifi & Mobile Office", "Operating Expenses", COMMON),

    # ---------------------------------------------- depreciation, amortisation
    ("Depreciation", "Depreciation and Amortisation", COMMON),
    # Pre-operative expenditure written off over time. The workbook put it in
    # this group; it is not a bank charge and not an operating cost.
    ("Administrative Expenses", "Depreciation and Amortisation", COMMON),

    # ---------------------------------------------------------- bank charges
    ("Bank Charges", "Bank and Finance Charges", COMMON),
    # Split out from Bank Charges so the insurance is legible on its own line.
    ("Bank Insurance", "Bank and Finance Charges", COMMON),
]

#: name -> (group, basis)
HEAD_INDEX = {name: (group, basis) for name, group, basis in HEADS}


def basis_of(account_name):
    """Building or Common for a head, or None if it is not one of ours.

    Takes either the bare account name or the full docname, since the caller
    usually has whichever ERPNext handed it.
    """
    if not account_name:
        return None
    name = str(account_name)
    entry = HEAD_INDEX.get(name)
    if entry:
        return entry[1]
    # Docnames are "Salary - DBR". Strip the abbreviation and try again.
    if " - " in name:
        entry = HEAD_INDEX.get(name.rsplit(" - ", 1)[0])
        if entry:
            return entry[1]
    return None


def group_of(account_name):
    """The P&L group a head prints under, or None."""
    if not account_name:
        return None
    name = str(account_name)
    entry = HEAD_INDEX.get(name)
    if not entry and " - " in name:
        entry = HEAD_INDEX.get(name.rsplit(" - ", 1)[0])
    return entry[0] if entry else None


def is_common(account_name):
    return basis_of(account_name) == COMMON


# ------------------------------------------------------------------ building

def _company():
    return (frappe.db.get_single_value("DBR Settings", "default_company")
            or frappe.defaults.get_global_default("company")
            or (frappe.get_all("Company", limit=1) or [{}])[0].get("name"))


def _expense_root(company):
    """A group account to hang the five P&L groups under."""
    for label in EXPENSE_PARENTS:
        acc = frappe.db.get_value("Account", {"account_name": label,
                                              "company": company,
                                              "is_group": 1}, "name")
        if acc:
            return acc
    return frappe.db.get_value(
        "Account", {"root_type": "Expense", "company": company,
                    "is_group": 1, "parent_account": ["is", "not set"]},
        "name") or frappe.db.get_value(
        "Account", {"root_type": "Expense", "company": company,
                    "is_group": 1}, "name")


def _ensure_account(name, company, parent, is_group=0):
    existing = frappe.db.get_value(
        "Account", {"account_name": name, "company": company}, "name")
    if existing:
        # A leaf that resolved to a group is the one failure mode that gets
        # all the way to a user: the chart builds without complaint, the entry
        # screen offers the head, and ERPNext refuses the posting only at
        # submit. Better to refuse to build than to ship that.
        was_group = frappe.db.get_value("Account", existing, "is_group")
        if bool(was_group) != bool(is_group):
            frappe.throw(
                "%s already exists on %s as a %s account. The expense chart "
                "needs it as a %s. Rename one of them before migrating."
                % (name, company, "group" if was_group else "leaf",
                   "group" if is_group else "leaf"))
        return existing, False
    doc = frappe.get_doc({
        "doctype": "Account",
        "account_name": name,
        "company": company,
        "parent_account": parent,
        "root_type": "Expense",
        "is_group": is_group,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name, True


def ensure_overhead_cost_center(company=None):
    """The single centre every common cost posts to."""
    company = company or _company()
    if not company:
        return None
    existing = frappe.db.get_value(
        "Cost Center", {"cost_center_name": OVERHEAD_COST_CENTER,
                        "company": company}, "name")
    if existing:
        return existing
    root = frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 1,
                        "parent_cost_center": ["is", "not set"]}, "name") \
        or frappe.db.get_value("Cost Center",
                               {"company": company, "is_group": 1}, "name")
    if not root:
        return None
    doc = frappe.get_doc({
        "doctype": "Cost Center",
        "cost_center_name": OVERHEAD_COST_CENTER,
        "parent_cost_center": root,
        "company": company,
        "is_group": 0,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def ensure_chart(company=None):
    """Create the five groups and every head under them. Idempotent.

    An account that already exists somewhere else on the chart is left where
    it is rather than moved: a head with postings against it can be reparented
    only by someone who has looked at those postings, and this runs unattended
    on every migrate. `report()` names the ones sitting outside their group so
    the move is a decision rather than a surprise.
    """
    company = company or _company()
    if not company:
        return {"created": [], "groups": [], "misplaced": [],
                "note": "No company on the site; chart not built."}

    root = _expense_root(company)
    if not root:
        return {"created": [], "groups": [], "misplaced": [],
                "note": "No expense group account to build under."}

    created, made_groups, misplaced = [], [], []
    group_names = {}
    for group, _label in GROUPS:
        name, made = _ensure_account(group, company, root, is_group=1)
        group_names[group] = name
        if made:
            made_groups.append(name)

    for head, group, _basis in HEADS:
        parent = group_names[group]
        name, made = _ensure_account(head, company, parent)
        if made:
            created.append(name)
        else:
            actual = frappe.db.get_value("Account", name, "parent_account")
            if actual != parent:
                misplaced.append({"account": name, "under": actual,
                                  "should_be": parent})

    ensure_overhead_cost_center(company)
    return {"created": created, "groups": made_groups,
            "misplaced": misplaced, "company": company}


def report(company=None):
    """What the chart looks like right now, without changing it."""
    company = company or _company()
    out = []
    for head, group, basis in HEADS:
        acc = frappe.db.get_value(
            "Account", {"account_name": head, "company": company}, "name")
        out.append({"head": head, "group": group, "basis": basis,
                    "account": acc, "exists": bool(acc)})
    return out
