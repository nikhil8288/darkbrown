"""Lay down the dummy portfolio by driving the application, not the database.

Every record here is created through the same whitelisted function the screen
calls. Onboarding goes through `portfolio.onboard_building`, a tenancy through
`agreements.create_agreement`, a bounce through `finance.return_cheque`. That
is the point: if the seed runs clean, the write path runs clean, and the
findings at the end are real findings rather than schema guesses.

Each step is wrapped. A step that fails is recorded and the run continues, so
one broken branch does not hide the state of the other twenty.
"""

import frappe
from frappe.utils import add_days, add_months, flt, get_first_day, getdate, today

from darkbrown.api import agreements as ag_api
from darkbrown.api import documents as doc_api
from darkbrown.api import finance as fin_api
from darkbrown.api import operations as ops_api
from darkbrown.api import portfolio as port_api
from darkbrown.demo import dataset as D
from darkbrown.demo import prereq

K = 1000.0


class Run:
    """Collects what happened so the caller gets one readable report."""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.steps = []
        self.findings = []
        self.made = {}

    def step(self, label, fn):
        try:
            out = fn()
            # Commit each step that lands. Without this a later failure rolls
            # the whole transaction back and quietly undoes work that had
            # already succeeded, which is how four maintenance jobs became
            # two and four documents became none.
            frappe.db.commit()
            self.steps.append((label, "ok", ""))
            if self.verbose:
                print(f"  ok    {label}")
            return out
        except Exception as e:
            msg = str(e).split("\n")[0][:160]
            self.steps.append((label, "FAILED", msg))
            self.findings.append(f"{label} — {msg}")
            if self.verbose:
                print(f"  FAIL  {label}\n        {msg}")
            frappe.db.rollback()
            return None

    def count(self, key, n=1):
        self.made[key] = self.made.get(key, 0) + n


def _months(n):
    """First day of the month n months from the current one."""
    return get_first_day(add_months(get_first_day(today()), n))


def _json(payload):
    return frappe.as_json(payload)


# ==========================================================================
#  main
# ==========================================================================

def run(verbose=True):
    r = Run(verbose)
    frappe.flags.ignore_permissions = True

    if verbose:
        print("\nprerequisites")
    r.step("company, banks, settings", lambda: prereq.ensure(verbose))

    if verbose:
        print("\nportfolio")
    keys = _buildings(r)
    _head_lease_schedules(r)
    _vacancies(r)

    if verbose:
        print("\nagreements")
    tenancies = _tenancies(r)

    if verbose:
        print("\ncheques")
    _cheques(r, tenancies)

    if verbose:
        print("\ninvoicing")
    _invoice_runs(r)

    if verbose:
        print("\nreceipts")
    _clear_cheques(r, tenancies)
    _cash_deposits(r)
    _bounce(r, tenancies)

    if verbose:
        print("\nhead lease payments")
    _pay_head_lease(r)

    if verbose:
        print("\noperations")
    _maintenance(r)
    _collections(r, tenancies)
    _moveout(r, tenancies)

    if verbose:
        print("\ndocuments and approvals")
    _documents(r)
    _amendment(r, tenancies)

    frappe.db.commit()
    return r


# ==========================================================================
#  portfolio
# ==========================================================================

def _buildings(r):
    made = {}
    for b in D.BUILDINGS:
        ll = D.LANDLORDS[b["landlord"]]
        hl = b["head_lease"]
        start = _months(hl["start_months"])
        payload = {
            "building_name": b["building_name"],
            "status": "Onboarding",
            "area_name": b["area_name"],
            "municipality": b["municipality"],
            "zone_no": b["zone_no"],
            "street_no": b["street_no"],
            "building_no": b["building_no"],
            "floors": b["floors"],
            "parking_spaces": b["parking_spaces"],
            "has_lift": b["has_lift"],
            "kahramaa_account_no": b["kahramaa_account_no"],
            "handover_date": _months(b["handover_months"]),
            "landlord": {
                "name": ll["name"], "qid": ll["qid"],
                "nationality": ll["nationality"], "iban": ll["iban"],
                "bank": ll["bank"],
            },
            "units": [{
                "unit_no": u["unit_no"], "floor": u["floor"],
                "unit_type": u["unit_type"], "status": "Vacant",
                "bedrooms": u["bedrooms"], "bathrooms": u["bathrooms"],
                "area_sqm": u["area_sqm"], "furnishing": u["furnishing"],
                "kahramaa_meter_no": u["meter"],
            } for u in b["units"]],
            "head_lease": {
                # the wizard collects thousands; the API multiplies by 1000
                "annual_rent": hl["annual_rent"] / K,
                "security_deposit": hl["security_deposit"] / K,
                "payment_frequency": hl["payment_frequency"],
                "start_date": start,
                "end_date": add_days(add_months(start, hl["months"]), -1),
            },
        }
        out = r.step(f"onboard {b['building_name']}",
                     lambda p=payload: port_api.onboard_building(_json(p)))
        if not out:
            continue
        made[b["key"]] = out["building"]
        r.count("buildings")
        r.count("units", out["units"])

        # A building only goes Active once it is handed over. The wizard
        # leaves it Onboarding, which is correct; this is the next step a
        # human would take.
        frappe.db.set_value("Building", out["building"], "status", "Active")

        # Utility meters, one Kahramaa per unit, so the utility bill has
        # something to allocate against.
        for u in b["units"]:
            unit = f"{out['building']}-{u['unit_no']}"
            if frappe.db.exists("Utility Meter", f"Kahramaa-{u['meter']}"):
                continue
            frappe.get_doc({
                "doctype": "Utility Meter", "building": out["building"],
                "unit": unit, "meter_type": "Kahramaa",
                "meter_no": u["meter"], "status": "Active",
            }).insert(ignore_permissions=True)

    frappe.db.commit()
    return made


def _head_lease_schedules(r):
    """The onboarding wizard creates the lease but not its payment schedule.

    A quarterly lease is four dated obligations, and the cash-out side of the
    spread cannot be seen without them.
    """
    def build():
        every = {"Monthly": 1, "Quarterly": 3, "Half Yearly": 6, "Annual": 12}
        n = 0
        for name in frappe.get_all("Head Lease", pluck="name"):
            hl = frappe.get_doc("Head Lease", name)
            if hl.payments:
                continue
            step = every.get(hl.payment_frequency, 3)
            per = flt(hl.annual_rent) * step / 12.0
            hl.monthly_rent = flt(hl.annual_rent) / 12.0
            due = getdate(hl.start_date)
            while due <= getdate(hl.end_date):
                hl.append("payments", {
                    "due_date": due,
                    "amount": per,
                    "payment_mode": "Cheque",
                    "status": "Scheduled",
                })
                due = add_months(due, step)
                n += 1
            hl.flags.ignore_mandatory = True
            hl.save(ignore_permissions=True)
        r.count("head lease instalments", n)
        return n

    r.step("head lease payment schedules", build)
    frappe.db.commit()


def _vacancies(r):
    def set_them():
        for unit, status in D.VACANCIES.items():
            if frappe.db.exists("Unit", unit):
                port_api.set_unit_status(unit, status)
        return len(D.VACANCIES)

    r.step("void and off-market units", set_them)


# ==========================================================================
#  agreements
# ==========================================================================

def _tenancies(r):
    """Returns {tenant name: agreement name} for the ones that went live."""
    made = {}
    for t in D.TENANCIES:
        bname = _building_name(t["building"])
        unit = f"{bname}-{t['unit']}"
        start = _months(t["start_months"])
        payload = {
            "unit": unit,
            "tenant": {
                "name": t["tenant"],
                "corporate": bool(t.get("corporate")),
                "qid": t.get("qid"),
                "cr_no": t.get("cr_no"),
                "mobile": t.get("mobile"),
                "qid_expiry": _months(18),
            },
            "start_date": start,
            "end_date": add_days(add_months(start, 12), -1),
            "rent": t["rent"] / K,
            "deposit": t["deposit"] / K,
            "payment_mode": t["mode"],
            # cheques_held is what makes an agreement self-approve; the real
            # cheques are logged in the next step and add to this.
            "cheques_held": t["cheques"],
            "qid": t.get("qid") if t["route"] != "override" else None,
            "mobile": t.get("mobile"),
            "signed_pack": (None if t["route"] == "pending"
                            else f"/files/signed/{unit.replace(' ', '_')}.pdf"),
            "deposit_method": "Cheque" if t["mode"] == "Cheque" else "Cash",
            "deposit_received_on": start,
            "charges": _charges(t),
        }
        out = r.step(f"tenancy {t['tenant']} · {unit}",
                     lambda p=payload: ag_api.create_agreement(_json(p)))
        if not out:
            continue
        r.count("tenancies")
        name = out["agreement"]
        made[t["tenant"]] = name

        if t["route"] == "override" and out["status"] == "Pending Approval":
            r.step(f"activate {name} on override",
                   lambda n=name: ag_api.activate(
                       n, "QID copy chased; tenant already in occupation."))
        elif t["route"] == "self" and out["status"] != "Active":
            r.findings.append(
                f"{t['tenant']} was expected to self-approve but landed "
                f"{out['status']} — missing: {', '.join(out.get('missing') or [])}")

    frappe.db.commit()
    return made


def _charges(t):
    """A few agreements carry a recurring charge, which is what puts a
    variance on the invoice run and sends it to the GM."""
    if t["unit"] in ("601", "S1"):
        return [{"type": "Parking", "amount": 0.5, "frequency": "Monthly",
                 "remarks": "Two reserved bays"}]
    if t["unit"] in ("101", "1A"):
        return [{"type": "Utilities", "amount": 0.35, "frequency": "Monthly",
                 "remarks": "Fixed water contribution"}]
    return []


def _building_name(key):
    for b in D.BUILDINGS:
        if b["key"] == key:
            return b["building_name"]
    return key


# ==========================================================================
#  cheques
# ==========================================================================

def _cheques(r, tenancies):
    for t in D.TENANCIES:
        if t["mode"] != "Cheque" or not t.get("first_cheque"):
            continue
        name = tenancies.get(t["tenant"])
        if not name:
            continue
        payload = {
            "tenancy_agreement": name,
            "direction": "Incoming",
            "cheque_no": t["first_cheque"],
            "cheque_date": _months(t["start_months"]),
            "amount": t["rent"] / K,
            "count": t["cheques"],
            "months_apart": 1,
            "bank": t.get("bank"),
        }
        out = r.step(f"PDCs for {t['tenant']} ({t['cheques']})",
                     lambda p=payload: fin_api.log_cheque(_json(p)))
        if out:
            r.count("cheques", out["count"])
    frappe.db.commit()


# ==========================================================================
#  invoicing
# ==========================================================================

def _invoice_runs(r):
    """Three months of rent, one run per building per month, issued."""
    for offset in (-2, -1, 0):
        period = _months(offset)
        for b in D.BUILDINGS:
            bname = b["building_name"]
            if not frappe.db.exists("Building", bname):
                continue
            label = f"invoice run {bname} {getdate(period):%b %Y}"
            out = r.step(label,
                         lambda n=bname, p=period: fin_api.build_invoice_run(n, p))
            if not out:
                continue
            run_name = out["run"]
            r.count("invoice runs")

            # A run carrying a variance goes to the GM first. The current
            # month's runs are left sitting there on purpose so the approvals
            # queue has something real in it.
            has_variance = frappe.db.get_value("Invoice Run", run_name,
                                               "has_variance")
            if has_variance:
                r.step(f"submit {run_name} to GM",
                       lambda n=run_name: fin_api.submit_invoice_run(n))
                if offset == 0 and bname == "Najma Tower":
                    continue          # left waiting, so the queue is not empty

            issued = r.step(f"issue {run_name}",
                            lambda n=run_name: fin_api.issue_invoice_run(n))
            if issued:
                r.count("sales invoices", issued.get("invoices", 0))
    frappe.db.commit()


# ==========================================================================
#  receipts
# ==========================================================================

# Two tenants are deliberately left behind so the collections module has
# something to work on.
ARREARS = {"Elena Petrova"}          # stopped paying two months ago
BOUNCER = "Deepak Sharma"            # latest cheque returns unpaid


def _clear_cheques(r, tenancies):
    """Present and clear the cheques that fall inside the invoiced window."""
    window_start = _months(-2)
    window_end = today()

    for t in D.TENANCIES:
        if t["mode"] != "Cheque":
            continue
        name = tenancies.get(t["tenant"])
        if not name:
            continue

        rows = frappe.get_all(
            "Cheque",
            filters={"tenancy_agreement": name, "status": "Received",
                     "cheque_date": ["between", [window_start, window_end]]},
            fields=["name", "cheque_date"], order_by="cheque_date asc")

        if t["tenant"] in ARREARS:
            rows = rows[:1]              # only the oldest clears

        for row in rows:
            def go(c=row.name, on=row.cheque_date):
                fin_api.present_cheque(c, None, on)
                return fin_api.clear_cheque(c, on)
            if r.step(f"clear cheque {row.name} · {t['tenant']}", go):
                r.count("cheques cleared")
    frappe.db.commit()


def _cash_deposits(r):
    """Cash rent, captured on a slip and banked as one batch.

    This is the path that matters most. Three quarters of what lands in the
    bank carries no payer name, so identity has to come from the slip, and
    the only way to test that is to move cash through it.
    """
    cash = [t for t in D.TENANCIES if t["mode"] == "Cash"]
    if not cash:
        return

    bank = frappe.db.get_single_value("DBR Settings", "default_bank_account")
    for i, offset in enumerate((-2, -1, 0)):
        month = _months(offset)
        slip = f"DBR-CASH-{getdate(month):%Y%m}"
        lines = []
        for j, t in enumerate(cash):
            bname = _building_name(t["building"])
            lines.append({
                "type": "Cash",
                "slip_no": f"{slip}-{j + 1:02d}",
                "tenant": t["tenant"],
                "unit": f"{bname}-{t['unit']}",
                "amount": t["rent"] / K,
                "remarks": f"Rent {getdate(month):%b %Y}, collected at unit",
            })
        payload = {"date": add_days(month, 2), "bank_account": bank,
                   "slip_no": slip, "lines": lines}

        out = r.step(f"cash deposit batch {slip}",
                     lambda p=payload: fin_api.create_deposit_batch(_json(p)))
        if not out:
            continue
        r.count("deposit batches")
        r.step(f"bank {out['batch']}",
               lambda b=out["batch"], d=add_days(month, 2):
               fin_api.deposit_batch(b, d))
    frappe.db.commit()


def _bounce(r, tenancies):
    """One returned cheque, which should reverse its money and open a case."""
    name = tenancies.get(BOUNCER)
    if not name:
        return
    # Deliberately one that has already cleared: bouncing it has to cancel
    # the Payment Entry and put the invoice back into arrears, which is the
    # part worth testing.
    row = frappe.get_all(
        "Cheque",
        filters={"tenancy_agreement": name, "status": "Cleared",
                 "cheque_date": ["between", [_months(-2), today()]]},
        fields=["name"], order_by="cheque_date desc", limit=1)
    if not row:
        r.findings.append(f"no cheque available to bounce for {BOUNCER}")
        return

    cheque = row[0].name
    out = r.step(
        f"return cheque {cheque} · {BOUNCER}",
        lambda: fin_api.return_cheque(
            cheque, "Insufficient Funds", charge=0.15,
            notes="Bank advice received. Tenant contacted the same day."))
    if out:
        r.count("returned cheques")
        if not out.get("case"):
            r.findings.append(
                "a returned cheque did not open a collection case")

    # A replacement cheque, so the replace path is exercised too.
    r.step(f"replacement for {cheque}",
           lambda: fin_api.replace_cheque(cheque, _json({
               "cheque_no": "995001",
               "cheque_date": add_days(today(), 7),
               "bank": "Commercial Bank of Qatar",
           })))
    frappe.db.commit()


def _pay_head_lease(r):
    """Settle the instalments that have already fallen due."""
    n = 0
    for name in frappe.get_all("Head Lease", pluck="name"):
        hl = frappe.get_doc("Head Lease", name)
        for line in hl.payments:
            if getdate(line.due_date) >= getdate(today()):
                continue
            if line.status in ("Cleared", "Presented"):
                continue
            out = r.step(
                f"pay head lease {name} due {line.due_date}",
                lambda h=name, row=line.name: fin_api.pay_head_lease(
                    h, row, _json({"mode": "Cheque"})))
            if out:
                n += 1
    r.count("head lease payments", n)
    frappe.db.commit()


# ==========================================================================
#  operations
# ==========================================================================

def _maintenance(r):
    for j in D.JOBS:
        if not frappe.db.exists("Building", j["building"]):
            continue
        payload = {
            "building": j["building"],
            "unit": j.get("unit"),
            "category": j["category"],
            "priority": j["priority"],
            "issue": j["issue"],
            "description": j["description"],
            "rechargeable": 1 if j.get("rechargeable") else 0,
            "recharge_to": j.get("recharge_to"),
            "recharge_amount": (j.get("recharge_amount") or 0) / K,
        }
        job = r.step(f"job — {j['issue']}",
                     lambda p=payload: ops_api.raise_job(_json(p)))
        if not job:
            continue
        r.count("maintenance jobs")
        if j.get("preventive"):
            frappe.db.set_value("Maintenance Request", job, "is_preventive", 1)

        for i, status in enumerate(j["advance"]):
            last = i == len(j["advance"]) - 1
            r.step(f"{job} → {status}",
                   lambda n=job, s=status, c=(j["cost"] / K if last else None):
                   ops_api.advance_job(
                       n, s, cost=c,
                       notes=("Attended and closed." if s == "Resolved"
                              else None)))
    frappe.db.commit()


def _collections(r, tenancies):
    """An arrears case worked through contact, promise and escalation."""
    name = tenancies.get("Elena Petrova")
    if not name:
        return

    case = r.step("open arrears case · Elena Petrova",
                  lambda: ops_api.open_case(
                      name, "Two months unpaid. Cheques stopped after the "
                            "first of the quarter."))
    if not case:
        return
    r.count("collection cases")

    r.step("log call", lambda: ops_api.log_contact(
        case, "Call", "No Answer",
        notes="Two attempts, no answer on either number."))
    r.step("log whatsapp", lambda: ops_api.log_contact(
        case, "WhatsApp", "Promised",
        notes="Says salary is delayed; offered to settle in full.",
        promised_amount=9.0, promised_date=add_days(today(), 10)))
    r.step("escalate case", lambda: ops_api.escalate(
        case, "Promise date passed with nothing received."))
    frappe.db.commit()


def _moveout(r, tenancies):
    """A move-out walked as far as settlement, left open on purpose."""
    name = tenancies.get("Anil Joseph Thomas")
    if not name:
        return

    case = r.step("open move-out · Najma Tower-501", lambda: ops_api.open_moveout(
        _json({"tenancy_agreement": name, "reason": "Tenant Notice",
               "notice_received_on": add_days(today(), -35),
               "planned_move_out": add_days(today(), 25)})))
    if not case:
        return
    r.count("move-out cases")

    r.step("move-out inspection", lambda: ops_api.advance_moveout(case, _json({
        "step": "inspection",
        "inspection_on": add_days(today(), -3),
        "notes": "Two doors scuffed, kitchen worktop chipped. Otherwise fair.",
        "damages": 1.2})))
    r.step("move-out meters", lambda: ops_api.advance_moveout(case, _json({
        "step": "meters",
        "readings": [
            {"meter_type": "Kahramaa", "meter_no": "K-501-27",
             "reading": 18422, "amount_due": 0.64},
            {"meter_type": "Water", "meter_no": "W-501-27",
             "reading": 2210, "amount_due": 0.18},
        ]})))
    r.step("move-out keys", lambda: ops_api.advance_moveout(case, _json({
        "step": "keys", "cards": 2})))

    # The deposit release only reaches the approvals queue if the deposit
    # knows about the move-out. `open_moveout` writes the link one way only.
    def link_deposit():
        sd = frappe.db.get_value("Security Deposit",
                                 {"tenancy_agreement": name}, "name")
        if not sd:
            return None
        frappe.db.set_value("Security Deposit", sd, {
            "move_out_case": case, "deductions": 1200})
        return sd

    if r.step("link deposit to move-out", link_deposit):
        r.findings.append(
            "Security Deposit.move_out_case is not written by "
            "operations.open_moveout — the demo sets it by hand, so the "
            "deposit-release approval would not otherwise appear")
    frappe.db.commit()


# ==========================================================================
#  documents and approvals
# ==========================================================================

def _documents(r):
    for d in D.DOCUMENTS:
        payload = {
            "file": f"/files/demo/{(d.get('document_no') or d['type'])}.pdf",
            "type": d["type"],
            "status": "Needs Review",
            "pages": 2,
            "party_type": d.get("party_type"),
            "party": d.get("party"),
            "building": d.get("building"),
            "unit": d.get("unit"),
            "document_no": d.get("document_no"),
            "issue_date": _months(d.get("issue_months", -1)),
            "expiry_date": (_months(d["expiry_months"])
                            if "expiry_months" in d else None),
            "confidence": 0.93,
            "model": "demo-seed",
        }
        out = r.step(f"register {d['type']} {d.get('document_no') or ''}".strip(),
                     lambda p=payload: doc_api.register(_json(p)))
        if not out:
            continue
        r.count("documents")
        name = out["document"]
        if d.get("reject"):
            r.step(f"reject {name}", lambda n=name, why=d["reject"]:
                   doc_api.review(n, "reject", _json({"reason": why})))
        elif d.get("confirm"):
            r.step(f"confirm {name}",
                   lambda n=name: doc_api.review(n, "confirm"))

    _supersede(r)
    frappe.db.commit()


def _supersede(r):
    """An expired QID replaced by its renewal. The old one should stop
    looking current the moment the new one is confirmed."""
    s = D.SUPERSESSION
    if not frappe.db.exists("Customer", s["party"]):
        return

    def register(spec, tag):
        out = doc_api.register(_json({
            "file": f"/files/demo/qid-{tag}.pdf",
            "type": "QID", "status": "Needs Review", "pages": 1,
            "party_type": "Customer", "party": s["party"],
            "document_no": spec["document_no"],
            "issue_date": _months(spec["issue_months"]),
            "expiry_date": _months(spec["expiry_months"]),
            "confidence": 0.95, "model": "demo-seed",
        }))
        doc_api.review(out["document"], "confirm")
        return out["document"]

    old = r.step(f"register superseded QID · {s['party']}",
                 lambda: register(s["old"], "old"))
    new = r.step(f"register renewed QID · {s['party']}",
                 lambda: register(s["new"], "new"))
    if old and new:
        r.count("documents", 2)
        if frappe.db.get_value("Document Register", old, "status") != "Superseded":
            r.findings.append(
                f"confirming the renewed QID left {old} at "
                f"{frappe.db.get_value('Document Register', old, 'status')} "
                f"rather than Superseded")


def _amendment(r, tenancies):
    """One rent increase above the MD threshold, left waiting for a decision,
    and one below it that the GM approves — so both routes are visible."""
    big = tenancies.get("Gulf Horizon Trading W.L.L.")
    small = tenancies.get("Sunita Menon")

    if big:
        out = r.step("amendment · Gulf Horizon rent review", lambda: (
            ag_api.request_amendment(_json({
                "agreement": big, "agreement_type": "Tenancy Agreement",
                "field": "monthly_rent", "old_value": "11500",
                "new_value": "12800",
                "value_impact": 15.6,      # QAR 15,600 over the year
                "effective_from": _months(1),
                "reason": "Market review at renewal. Two comparable 3 BHK "
                          "units in the same zone are letting at 13,000.",
            }))))
        if out:
            r.count("amendments")

    if small:
        out = r.step("amendment · Sunita Menon parking added", lambda: (
            ag_api.request_amendment(_json({
                "agreement": small, "agreement_type": "Tenancy Agreement",
                "field": "monthly_rent", "old_value": "6500",
                "new_value": "6800",
                "value_impact": 3.6,
                "effective_from": _months(1),
                "reason": "Tenant has taken a second parking bay.",
            }))))
        if out:
            r.count("amendments")
            r.step("GM approves the small amendment",
                   lambda n=out["amendment"]: ag_api.decide_amendment(
                       n, "approve", "Within delegated authority."))

    # A utility bill, allocated across the units it covers.
    _utility_bill(r)


def _utility_bill(r):
    building = "Najma Tower"
    if not frappe.db.exists("Building", building):
        return

    def make():
        units = frappe.get_all("Unit", filters={"building": building},
                               fields=["name"], order_by="name")
        if not units:
            return None
        total = 9800.0
        share = round(total / len(units), 2)
        # the last row carries the rounding remainder, so the parts can never
        # add up to more than the bill
        last = round(total - share * (len(units) - 1), 2)
        doc = frappe.get_doc({
            "doctype": "Utility Bill",
            "building": building,
            "utility_type": "Kahramaa",
            "status": "Draft",
            "company": frappe.db.get_single_value("DBR Settings",
                                                  "default_company"),
            "bill_no": "KM-INV-889201",
            "period_start": _months(-1),
            "period_end": add_days(_months(0), -1),
            "amount": total,
            "consumption": 14200,
            "allocation_basis": "Sub-Meter",
        })
        for u in units:
            tenant = frappe.db.get_value(
                "Tenancy Agreement",
                {"unit": u.name, "status": "Active"}, "tenant")
            doc.append("allocations", {
                "unit": u.name, "tenant": tenant,
                "share_pct": round(100.0 / len(units), 2),
                "consumption": round(14200.0 / len(units), 1),
                "amount": last if u.name == units[-1].name else share,
            })
        doc.allocated_total = sum(a.amount for a in doc.allocations)
        doc.unallocated = total - doc.allocated_total
        doc.status = "Allocated"
        doc.flags.ignore_mandatory = True
        doc.insert(ignore_permissions=True)
        return doc.name

    if r.step("utility bill · Najma Tower Kahramaa", make):
        r.count("utility bills")
