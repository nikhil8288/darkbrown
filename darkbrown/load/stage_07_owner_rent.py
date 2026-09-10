"""Stage 7 — owner rent paid.

Two files, because two different kinds of thing are being loaded and only one
of them is evidence.

`owner_cheques.csv` is the cheque register: 388 cheques, each with its own
number, date, bank and amount. That is a record of something that happened.

`owner_transfers.csv` is not. It is 48 building-periods where the owner-rent
register shows rent paid that no cheque accounts for, and the amount is
arrived at by subtraction. Every row carries `derived = 1` and says so in its
note, and the payments are written with `payment_mode = Transfer`. If a bank
statement is loaded later these should be replaced by the real entries, not
added to.

**One cheque is one record.** 111 of the 388 pay the ten Al Adekhar villas
together, and the register never says which villas a given cheque covers —
the amounts run 16,000 / 32,000 / 48,000 / 64,000, so each pays one, two,
three or four of them. Splitting a cheque ten ways would produce ten records
none of which matches anything a bank will ever show. They carry no building
and say what they cover instead.

**The register had to be deduplicated before any of this was true.** It holds
several overlapping blocks under different property names: 230 rows collapsed,
including 105 villa cheques that appear a second time labelled DAFNA VILLA
with the bank column blank. Cheque numbers repeat across banks, so the key is
number, date, amount and building together — number alone would have merged
two unrelated cheques.

**Cheques dated after 31 July 2026 are Presented, not Cleared.** 288 of them
are post-dated, some out to 2028. They are real commitments and belong on the
site, but they are not cash that has moved.
"""

import frappe

from darkbrown.load import common as C

STAGE = "7"
CHEQUES = "owner_cheques.csv"
TRANSFERS = "owner_transfers.csv"

CUTOFF = "2026-07-31"
STATUSES = ("Received", "Deposited", "Presented", "Cleared", "Returned",
            "Replaced", "Cancelled")


def _money(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _resolve(rows, xrows):
    buildings = set(frappe.get_all("Building", pluck="name"))
    suppliers = set(frappe.get_all("Supplier", pluck="name"))
    leases = {}
    for h in frappe.get_all("Head Lease", fields=["name", "building",
                                                  "status"]):
        leases.setdefault(h.building, []).append(h)

    existing = {}
    for c in frappe.get_all("Cheque",
                            fields=["name", "cheque_no", "cheque_date",
                                    "amount"]):
        existing[(c.cheque_no, str(c.cheque_date or ""),
                  round(float(c.amount or 0), 2))] = c.name

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        no = (r.get("cheque_no") or "").strip()
        b = (r.get("building") or "").strip()
        date = (r.get("cheque_date") or "").strip()
        amount = _money(r.get("amount"))

        def bad(column, value, rule, message):
            problems.append(C.Problem(CHEQUES, i, column, value, rule, message))

        if not no:
            bad("cheque_no", no, "cheque_no_required",
                "a cheque without a number cannot be reconciled to a bank")
            continue
        key = (no, date, amount, b)
        if key in seen:
            bad("cheque_no", no, "duplicate_in_file",
                "same cheque as row %d" % seen[key])
            continue
        seen[key] = i

        if amount is None or amount <= 0:
            bad("amount", r.get("amount"), "amount_required",
                "not a positive amount")
        if b and b not in buildings:
            bad("building", b, "building_unresolved",
                "no Building on the site")
        landlord = (r.get("landlord") or "").strip()
        if landlord and landlord not in suppliers:
            bad("landlord", landlord, "landlord_unresolved",
                "no Supplier on the site — stage 1 must be gated first")
        status = (r.get("status") or "").strip()
        if status not in STATUSES:
            bad("status", status, "status_unknown",
                "not one of the doctype's options")
        if date and date <= CUTOFF and status != "Cleared":
            bad("status", status, "past_but_not_cleared",
                "dated on or before the cutover and not marked Cleared")
        if date and date > CUTOFF and status == "Cleared":
            bad("status", status, "future_but_cleared",
                "post-dated cheques are commitments, not cash that has moved")
        # `cheque_date` is mandatory on the doctype, and for a cheque that
        # will be presented it should be. A security cheque genuinely has
        # none, so those are inserted with `ignore_mandatory` rather than the
        # doctype being loosened for every cheque in the system. The rules
        # below are what replaces the field-level check for those rows.
        if not date:
            if not (r.get("undated_reason") or "").strip():
                bad("cheque_date", date, "undated_without_reason",
                    "a cheque with no date must say why it has none")
            if status != "Received":
                bad("status", status, "undated_not_received",
                    "an undated cheque is held, not presented or cleared")

        lease = None
        for h in (leases.get(b) or []):
            lease = h["name"]
            if h["status"] == "Active":
                break
        plan.append({"row": i, "raw": r, "no": no, "building": b,
                     "landlord": landlord, "date": date, "amount": amount,
                     "status": status, "lease": lease,
                     "security": (r.get("is_security") or "").strip() == "1",
                     "existing": existing.get((no, date, amount))})

    xplan = []
    for i, r in enumerate(xrows, start=2):
        b = (r.get("building") or "").strip()
        amount = _money(r.get("amount"))

        def xbad(column, value, rule, message):
            problems.append(C.Problem(TRANSFERS, i, column, value, rule,
                                      message))

        if b not in buildings:
            xbad("building", b, "building_unresolved", "no Building on the site")
        if amount is None or amount <= 0:
            xbad("amount", r.get("amount"), "amount_required",
                 "not a positive amount")
        if (r.get("derived") or "").strip() != "1":
            xbad("derived", r.get("derived"), "not_flagged_derived",
                 "a transfer with no bank reference must say so")
        lease = None
        for h in (leases.get(b) or []):
            lease = h["name"]
            if h["status"] == "Active":
                break
        if not lease:
            xbad("building", b, "no_head_lease",
                 "the payment has no lease to hang from")
        xplan.append({"row": i, "raw": r, "building": b, "amount": amount,
                      "lease": lease,
                      "due": (r.get("period_end") or "").strip()})
    return plan, xplan, problems


def _split(plan):
    past = [p for p in plan if p["date"] and p["date"] <= CUTOFF
            and not p["security"]]
    future = [p for p in plan if p["date"] and p["date"] > CUTOFF]
    undated = [p for p in plan if not p["date"]]
    return past, future, undated


def check():
    rows, xrows = C.rows(CHEQUES), C.rows(TRANSFERS)
    plan, xplan, problems = _resolve(rows, xrows)
    past, future, undated = _split(plan)
    fresh = [p for p in plan if not p["existing"]]
    multi = [p for p in plan if not p["building"]]

    def q(v):
        return frappe.utils.fmt_money(v, currency="QAR")

    def total(rs):
        return sum(p["amount"] for p in rs)

    print("STAGE 7 CHECK — owner rent paid")
    print("  %s: %d cheque(s), %s to create"
          % (CHEQUES, len(rows), len(fresh)))
    print("  cleared up to %s   %3d   %s" % (CUTOFF, len(past), q(total(past))))
    print("  post-dated             %3d   %s"
          % (len(future), q(total(future))))
    print("  undated / security     %3d   %s"
          % (len(undated), q(total(undated))))
    for p in undated:
        print("        %-9s %-9s %12s  %s"
              % (p["no"], p["building"] or "(villas)", q(p["amount"]),
                 p["raw"].get("undated_reason", "")))
    print("  %d cheque(s) pay the ten villas together and carry no building "
          "— the register never says which villas" % len(multi))
    print("  %s: %d derived transfer(s), %s"
          % (TRANSFERS, len(xplan),
             q(sum(p["amount"] for p in xplan if p["amount"]))))
    print("      these have no bank reference. They are booked owner rent "
          "less cheques, and should be replaced if a statement is loaded.")
    C.report(problems)
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "problems": len(problems),
            "clean": not problems}


def run():
    rows, xrows = C.rows(CHEQUES), C.rows(TRANSFERS)
    plan, xplan, problems = _resolve(rows, xrows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 7 refused: %d problem(s). Run Check."
                     % len(problems))

    company = C.company()
    made, failed, lines = 0, [], 0
    print("STAGE 7 RUN — owner rent paid")

    for p in plan:
        if p["existing"]:
            continue
        r = p["raw"]
        try:
            c = frappe.new_doc("Cheque")
            c.direction = "Outgoing"
            c.party_type = "Supplier"
            c.party = p["landlord"]
            c.company = company
            c.cheque_no = p["no"]
            c.cheque_date = p["date"] or None
            c.amount = p["amount"]
            c.status = p["status"]
            if r.get("bank"):
                c.bank = r["bank"]
            if p["building"]:
                c.building = p["building"]
            if p["lease"]:
                c.head_lease = p["lease"]
            if p["date"] and p["date"] <= CUTOFF:
                c.cleared_on = p["date"]
            c.flags.ignore_permissions = True
            if not p["date"]:
                # held undated, with the reason recorded on the row. Checked
                # above; nothing else is allowed through without a date.
                c.flags.ignore_mandatory = True
            c.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            failed.append((p["no"], (text.splitlines() or ["?"])[0][:90]))

    # the derived transfers hang off the lease, not off a cheque
    for p in xplan:
        if not p["lease"]:
            continue
        try:
            hl = frappe.get_doc("Head Lease", p["lease"])
            already = any(getattr(x, "due_date", None)
                          and str(x.due_date) == p["due"]
                          and round(float(x.amount or 0), 2) == p["amount"]
                          and x.payment_mode == "Transfer"
                          for x in (hl.payments or []))
            if already:
                continue
            hl.append("payments", {"due_date": p["due"], "amount": p["amount"],
                                   "payment_mode": "Transfer",
                                   "status": "Cleared", "paid_on": p["due"]})
            hl.flags.ignore_permissions = True
            hl.save()
            frappe.db.commit()
            lines += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            failed.append(("transfer %s %s" % (p["building"], p["due"]),
                           (text.splitlines() or ["?"])[0][:90]))

    if failed:
        C.report([C.Problem(CHEQUES, "-", "cheque_no", n, "insert_failed", w)
                  for n, w in failed])
    print("  created %d cheque(s) and %d transfer line(s)" % (made, lines))
    print("  Now press Gate.")
    return {"created": made, "transfers": lines, "failed": len(failed)}


def reload():
    print("STAGE 7 RELOAD — owner rent paid")
    return run()


def gate():
    rows, xrows = C.rows(CHEQUES), C.rows(TRANSFERS)
    plan, xplan, problems = _resolve(rows, xrows)
    past, future, undated = _split(plan)

    on_site = frappe.db.count("Cheque", {"direction": "Outgoing"})
    cleared = frappe.db.count("Cheque", {"direction": "Outgoing",
                                         "status": "Cleared"})
    presented = frappe.db.count("Cheque", {"direction": "Outgoing",
                                           "status": "Presented"})
    held = frappe.db.count("Cheque", {"direction": "Outgoing",
                                      "status": "Received"})
    site_total = round(sum(float(c.amount or 0) for c in frappe.get_all(
        "Cheque", filters={"direction": "Outgoing"}, fields=["amount"])), 2)
    want_total = round(sum(p["amount"] for p in plan), 2)

    orphan = len([c for c in frappe.get_all(
        "Cheque", filters={"direction": "Outgoing"}, fields=["name", "party"])
        if not frappe.db.exists("Supplier", c.party)])

    xfer = 0
    for h in frappe.get_all("Head Lease", pluck="name"):
        doc = frappe.get_doc("Head Lease", h)
        xfer += len([x for x in (doc.payments or [])
                     if x.payment_mode == "Transfer"])

    checks = [
        ("every cheque in the register exists", on_site == len(plan),
         "%d on site vs %d expected" % (on_site, len(plan))),
        ("the amounts reconcile", abs(site_total - want_total) < 1.0,
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(site_total, currency="QAR"),
            frappe.utils.fmt_money(want_total, currency="QAR"))),
        ("cheques up to the cutover are Cleared", cleared == len(past),
         "%d Cleared vs %d dated on or before %s"
         % (cleared, len(past), CUTOFF)),
        ("post-dated cheques are not Cleared", presented == len(future),
         "%d Presented vs %d post-dated" % (presented, len(future))),
        ("undated cheques are held, not cleared", held == len(undated),
         "%d Received vs %d undated" % (held, len(undated))),
        ("no cheque points at a landlord that is gone", not orphan,
         "%d orphan(s)" % orphan),
        ("the derived transfers are on their leases", xfer == len(xplan),
         "%d transfer line(s) vs %d expected" % (xfer, len(xplan))),
        ("both worksheets still resolve cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
