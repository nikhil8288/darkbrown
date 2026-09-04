"""Bulk import of the live tenancy book.

Roughly 250 agreements are already in force. They exist on paper and in
spreadsheets; until they are Tenancy Agreement records nothing downstream
works - no rent invoicing, no arrears, no occupancy, no collection cases.

    STEP 1  bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.template
            prints the column contract; build tenancies.csv to match
    STEP 2  bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.dry_run
    STEP 3  resolve everything dry_run refuses; re-run dry_run
    STEP 4  bench --site erp.darkbrown.qa execute darkbrown.patches.import_tenancies.run

WHY IT REFUSES RATHER THAN GUESSES

Same rule as the other two importers. A stopped run costs a morning; a wrong
tenancy invoices a tenant for someone else's flat and is found months later.
run() aborts on any unmatched tenant, unmatched unit, ambiguous name, end date
on or before its start, duplicate key inside the CSV, or a second live tenancy
landing on a unit that already has one. Nothing is created until every row is
clean, and no Customer is ever auto-created.

ACTIVATION - read this before running

TenancyAgreement.validate() routes an agreement for approval when the QID or
the signed pack is missing, and pushes Draft to Pending Approval. For a
migration that is the wrong instinct: these agreements ARE live and signed, the
scans just are not in the system yet. Left to default, all ~250 would land as
Pending Approval, and because unit occupancy follows tenancy status the whole
portfolio would read Vacant.

So `status` is set explicitly (default Active). The controller does not
downgrade a status that is already Active - it records `missing_items` and sets
`activation_route = "Routed for Approval"`, which is exactly right: the ledger
is correct from day one and missing_items becomes an honest worklist of which
packs still need scanning. dry_run reports that count so it is not a surprise.

IDEMPOTENCY

Keyed on (unit, start_date). A unit cannot have two tenancies beginning on the
same day, so a re-run after a partial failure skips precisely what it created.

This module is deliberately NOT a Frappe patch. It is bench-execute only: a
patch runs unattended during a deploy, and this one writes the tenancy book.
"""
import collections
import csv
import os
import re

import frappe
from frappe.utils import flt, getdate

CSV = os.path.join(os.path.dirname(__file__), "tenancies.csv")
NAME_MAP = os.path.join(os.path.dirname(__file__), "tenancy_name_map.csv")
CHARGES_CSV = os.path.join(os.path.dirname(__file__), "tenancy_charges.csv")

LIVE = ("Active", "Expiring")

TA_STATUS = ("Draft", "Pending Approval", "Active", "Expiring",
             "Expired", "Terminated")
PAY_MODE = ("Cheque", "Cash", "Transfer")
PAY_FREQ = ("Monthly", "Quarterly", "Half Yearly", "Annual")
CHARGE_TYPE = ("Utilities", "Parking", "Maintenance Recharge", "Service",
               "Other")
CHARGE_FREQ = ("Monthly", "Quarterly", "One Time")

COLUMNS = [
    ("tenant_name", "required unless tenant_id given; matched exactly"),
    ("tenant_id", "optional Customer docname; wins over tenant_name"),
    ("building", "Building docname; with unit_no forms the Unit key"),
    ("unit_no", "unit number exactly as on the Unit record"),
    ("unit", "optional full Unit docname; wins over building+unit_no"),
    ("start_date", "YYYY-MM-DD"),
    ("end_date", "YYYY-MM-DD; must be after start_date"),
    ("monthly_rent", "QAR, number only"),
    ("security_deposit", "QAR; blank or 0 if none"),
    ("payment_mode", "/".join(PAY_MODE) + "  (default Cheque)"),
    ("payment_frequency", "/".join(PAY_FREQ) + "  (default Monthly)"),
    ("cheques_held", "integer; blank = 0"),
    ("status", "/".join(TA_STATUS) + "  (default Active)"),
    ("notice_days", "integer; blank = DBR Settings default"),
    ("auto_renew", "1 or 0; blank = 0"),
    ("qid_number", "optional; blank leaves missing_items set"),
    ("qid_expiry", "YYYY-MM-DD, optional"),
    ("passport_no", "optional"),
    ("mobile_no", "optional"),
    ("notes", "optional free text"),
]

CHARGE_COLUMNS = [
    ("building", "matches the tenancy row"),
    ("unit_no", "matches the tenancy row"),
    ("start_date", "matches the tenancy row - this is the join key"),
    ("charge_type", "/".join(CHARGE_TYPE)),
    ("amount", "QAR, number only"),
    ("frequency", "/".join(CHARGE_FREQ) + "  (default Monthly)"),
    ("remarks", "optional"),
]


# ---------------------------------------------------------------- template

def template():
    """Print the column contract, so the sheet is built to fit the importer
    rather than the importer guessed at afterwards."""
    print("=" * 76)
    print("tenancies.csv  ->  darkbrown/patches/tenancies.csv")
    print("=" * 76)
    print(",".join(c for c, _ in COLUMNS))
    print()
    for c, note in COLUMNS:
        print("  %-20s %s" % (c, note))
    print()
    print("Unit is resolved as `unit` if given, else `{building}-{unit_no}`,")
    print("which is how Unit records are named. Tenant is `tenant_id` if")
    print("given, else an exact normalised match on Customer name, else a")
    print("line in tenancy_name_map.csv:")
    print()
    print("    tenant_name,customer")
    print('    "THASMEER/ SHAMNADH",CUST-00042')
    print()
    print("=" * 76)
    print("tenancy_charges.csv (OPTIONAL)  -> recurring charges beyond rent")
    print("=" * 76)
    print(",".join(c for c, _ in CHARGE_COLUMNS))
    print()
    for c, note in CHARGE_COLUMNS:
        print("  %-20s %s" % (c, note))
    print()
    print("Omit the file entirely if there are no separate charges.")


# ---------------------------------------------------------------- matching

def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def _customer_index():
    idx = {}
    for c in frappe.get_all("Customer", fields=["name", "customer_name"]):
        idx.setdefault(_norm(c.customer_name), []).append(c.name)
    return idx


def _name_map():
    if not os.path.exists(NAME_MAP):
        return {}
    out = {}
    with open(NAME_MAP, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            k = _norm(row.get("tenant_name"))
            v = (row.get("customer") or "").strip()
            if k and v:
                out[k] = v
    return out


def _match_tenant(row, idx, overrides):
    explicit = (row.get("tenant_id") or "").strip()
    if explicit:
        if frappe.db.exists("Customer", explicit):
            return explicit, "id"
        return None, "tenant_id not found"
    n = _norm(row.get("tenant_name"))
    if not n:
        return None, "no tenant_name"
    if n in overrides:
        c = overrides[n]
        return ((c, "mapped") if frappe.db.exists("Customer", c)
                else (None, "map target missing"))
    hit = idx.get(n)
    if not hit:
        return None, "unmatched"
    if len(hit) > 1:
        return None, "ambiguous (%d customers)" % len(hit)
    return hit[0], "exact"


def _match_unit(row):
    explicit = (row.get("unit") or "").strip()
    if explicit:
        return ((explicit, "id") if frappe.db.exists("Unit", explicit)
                else (None, "unit not found"))
    b = (row.get("building") or "").strip()
    u = (row.get("unit_no") or "").strip()
    if not (b and u):
        return None, "no building/unit_no"
    if not frappe.db.exists("Building", b):
        return None, "building %r not found" % b
    name = "%s-%s" % (b, u)          # Unit autoname: format:{building}-{unit_no}
    if frappe.db.exists("Unit", name):
        return name, "exact"
    hit = frappe.get_all("Unit", filters={"building": b, "unit_no": u},
                         pluck="name")
    if len(hit) == 1:
        return hit[0], "by field"
    if len(hit) > 1:
        return None, "ambiguous (%d units)" % len(hit)
    return None, "no unit %r in %r" % (u, b)


# ---------------------------------------------------------------- validation

def _pick(value, allowed, default):
    v = (value or "").strip()
    if not v:
        return default, None
    for a in allowed:
        if v.lower() == a.lower():
            return a, None
    return default, "%r is not one of %s" % (v, "/".join(allowed))


def _rows(path=None):
    path = path or CSV
    if not os.path.exists(path):
        frappe.throw("%s not found. Run template() and build it first." % path)
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _charge_rows():
    if not os.path.exists(CHARGES_CSV):
        return {}
    out = collections.defaultdict(list)
    with open(CHARGES_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = ((r.get("building") or "").strip(),
                   (r.get("unit_no") or "").strip(),
                   str(r.get("start_date") or "").strip())
            out[key].append(r)
    return out


def _resolve(rows, idx, overrides):
    """Returns (resolved, problems). Nothing touches the database here except
    lookups - this is the same pass dry_run and run both use, so what you were
    shown is what runs."""
    resolved, problems = [], []
    seen_keys = {}

    for i, r in enumerate(rows):
        line = i + 2                      # header is line 1
        errs = []

        tenant, how_t = _match_tenant(r, idx, overrides)
        if not tenant:
            errs.append("tenant: %s" % how_t)
        unit, how_u = _match_unit(r)
        if not unit:
            errs.append("unit: %s" % how_u)

        try:
            start = getdate(r.get("start_date"))
        except Exception:
            start, errs = None, errs + ["start_date unreadable"]
        try:
            end = getdate(r.get("end_date"))
        except Exception:
            end, errs = None, errs + ["end_date unreadable"]
        if start and end and end <= start:
            errs.append("end_date %s is not after start_date %s" % (end, start))

        rent = flt(r.get("monthly_rent"))
        if rent <= 0:
            errs.append("monthly_rent must be > 0")

        status, e = _pick(r.get("status"), TA_STATUS, "Active")
        if e:
            errs.append("status " + e)
        mode, e = _pick(r.get("payment_mode"), PAY_MODE, "Cheque")
        if e:
            errs.append("payment_mode " + e)
        freq, e = _pick(r.get("payment_frequency"), PAY_FREQ, "Monthly")
        if e:
            errs.append("payment_frequency " + e)

        key = (unit, str(start)) if unit and start else None
        if key:
            if key in seen_keys:
                errs.append("duplicate of CSV line %d (same unit and "
                            "start_date)" % seen_keys[key])
            else:
                seen_keys[key] = line

        rec = {
            "line": line, "row": r, "tenant": tenant, "unit": unit,
            "start": start, "end": end, "rent": rent, "status": status,
            "mode": mode, "freq": freq, "key": key,
            "how": "%s/%s" % (how_t, how_u),
        }
        if errs:
            problems.append((rec, errs))
        else:
            resolved.append(rec)
    return resolved, problems


def _existing_keys():
    """(unit, start_date) already on a Tenancy Agreement."""
    return {(a.unit, str(a.start_date)) for a in frappe.get_all(
        "Tenancy Agreement", fields=["unit", "start_date"])}


def _live_conflicts(resolved, existing):
    """A unit may hold only one LIVE tenancy. Checks incoming rows against each
    other and against what is already on the site."""
    out = []
    incoming_live = collections.defaultdict(list)
    for rec in resolved:
        if rec["status"] in LIVE:
            incoming_live[rec["unit"]].append(rec)

    for unit, recs in incoming_live.items():
        if len(recs) > 1:
            out.append((unit, "CSV lines %s all claim this unit as live"
                        % ", ".join(str(r["line"]) for r in recs)))
            continue
        rec = recs[0]
        if rec["key"] in existing:
            continue                      # this row IS the existing record
        held = frappe.get_all(
            "Tenancy Agreement",
            filters={"unit": unit, "status": ["in", LIVE]}, pluck="name")
        if held:
            out.append((unit, "CSV line %d is live but %s already holds it"
                        % (rec["line"], held[0])))
    return out


# ---------------------------------------------------------------- commands

def dry_run():
    rows = _rows()
    idx = _customer_index()
    overrides = _name_map()
    resolved, problems = _resolve(rows, idx, overrides)
    existing = _existing_keys()
    conflicts = _live_conflicts(resolved, existing)
    charges = _charge_rows()

    already = [r for r in resolved if r["key"] in existing]
    to_make = [r for r in resolved if r["key"] not in existing]
    no_qid = [r for r in to_make if not (r["row"].get("qid_number") or "").strip()]

    print("=" * 78)
    print("DRY RUN - nothing created")
    print("rows %d | clean %d | PROBLEMS %d | already imported %d | to create %d"
          % (len(rows), len(resolved), len(problems), len(already), len(to_make)))
    print("-" * 78)
    for r in to_make[:400]:
        ch = len(charges.get((
            (r["row"].get("building") or "").strip(),
            (r["row"].get("unit_no") or "").strip(),
            str(r["row"].get("start_date") or "").strip()), []))
        print("new  L%-4d %-22s %-20s %s..%s  QAR %9s  %-8s%s"
              % (r["line"], r["unit"][:22], r["tenant"][:20], r["start"],
                 r["end"], format(r["rent"], ",.0f"), r["status"],
                 ("  +%d charge(s)" % ch) if ch else ""))
    if len(to_make) > 400:
        print("... %d more" % (len(to_make) - 400))

    if problems:
        print("-" * 78)
        print("PROBLEMS - run() WILL ABORT until every one is resolved:")
        for rec, errs in problems:
            print("  L%-4d %-28s %s"
                  % (rec["line"], (rec["row"].get("tenant_name") or "")[:28],
                     "; ".join(errs)))
        unmatched = sorted({(p[0]["row"].get("tenant_name") or "").strip()
                            for p in problems
                            if any(e.startswith("tenant:") for e in p[1])})
        if unmatched:
            print()
            print("  Add a line per name to tenancy_name_map.csv:")
            print()
            print("  tenant_name,customer")
            for n in unmatched:
                print('  "%s",' % n)

    if conflicts:
        print("-" * 78)
        print("LIVE TENANCY CONFLICTS - run() WILL ABORT:")
        for unit, msg in conflicts:
            print("  %-24s %s" % (unit, msg))

    print("-" * 78)
    total = sum(r["rent"] for r in resolved if r["status"] in LIVE)
    print("monthly rent roll across live rows: QAR %s" % format(total, ",.2f"))
    if no_qid:
        print("%d of the %d to create have no QID. They will still be created "
              "Active;" % (len(no_qid), len(to_make)))
        print("the controller records missing_items and flags them for "
              "approval, which")
        print("is the worklist of packs still to be scanned - not a blocker.")
    if not problems and not conflicts:
        print()
        print("CLEAN - run() will create %d agreements." % len(to_make))
    return {"rows": len(rows), "clean": len(resolved),
            "problems": len(problems), "conflicts": len(conflicts),
            "to_create": len(to_make)}


def run():
    rows = _rows()
    idx = _customer_index()
    overrides = _name_map()
    resolved, problems = _resolve(rows, idx, overrides)

    if problems:
        print("ABORTING: %d rows have problems. Nothing was created."
              % len(problems))
        print("Run dry_run for the list. This importer never auto-creates a")
        print("Customer and never guesses a unit.")
        return {"created": 0, "skipped": 0, "aborted": True}

    existing = _existing_keys()
    conflicts = _live_conflicts(resolved, existing)
    if conflicts:
        print("ABORTING: %d unit(s) would end up with two live tenancies."
              % len(conflicts))
        for unit, msg in conflicts:
            print("  %-24s %s" % (unit, msg))
        return {"created": 0, "skipped": 0, "aborted": True}

    settings = frappe.get_single("DBR Settings")
    company = (settings.default_company
               or frappe.db.get_value("Company", {}, "name"))
    default_notice = int(settings.default_tenancy_notice_days or 60)
    charges = _charge_rows()

    made = skipped = charge_rows = 0
    for rec in resolved:
        if rec["key"] in existing:
            skipped += 1
            continue
        r = rec["row"]
        doc = frappe.new_doc("Tenancy Agreement")
        doc.update({
            "tenant": rec["tenant"],
            "unit": rec["unit"],
            "building": frappe.db.get_value("Unit", rec["unit"], "building"),
            "company": company,
            # Explicit. Left to the controller's default these would all land
            # as Pending Approval and every unit would read Vacant.
            "status": rec["status"],
            "start_date": rec["start"],
            "end_date": rec["end"],
            "notice_days": int(r.get("notice_days") or default_notice),
            "auto_renew": 1 if str(r.get("auto_renew") or "").strip() in
                          ("1", "yes", "Yes", "true", "True") else 0,
            "monthly_rent": rec["rent"],
            "security_deposit": flt(r.get("security_deposit")),
            "payment_mode": rec["mode"],
            "payment_frequency": rec["freq"],
            "cheques_held": int(flt(r.get("cheques_held"))),
            "qid_number": (r.get("qid_number") or "").strip() or None,
            "qid_expiry": (r.get("qid_expiry") or "").strip() or None,
            "passport_no": (r.get("passport_no") or "").strip() or None,
            "mobile_no": (r.get("mobile_no") or "").strip() or None,
            "notes": (r.get("notes") or "").strip() or None,
        })
        for c in charges.get(((r.get("building") or "").strip(),
                              (r.get("unit_no") or "").strip(),
                              str(r.get("start_date") or "").strip()), []):
            ctype, _e = _pick(c.get("charge_type"), CHARGE_TYPE, "Other")
            cfreq, _e = _pick(c.get("frequency"), CHARGE_FREQ, "Monthly")
            doc.append("charges", {
                "charge_type": ctype,
                "amount": flt(c.get("amount")),
                "frequency": cfreq,
                "remarks": (c.get("remarks") or "").strip() or None,
            })
            charge_rows += 1
        doc.flags.ignore_permissions = True
        doc.insert()
        made += 1

    frappe.db.commit()
    print("created %d agreements (%d charge rows), skipped %d already present"
          % (made, charge_rows, skipped))
    routed = frappe.db.count("Tenancy Agreement",
                             {"activation_route": "Routed for Approval"})
    if routed:
        print("%d agreements carry missing_items - that is the documentation "
              "worklist" % routed)
        print("(QID or signed pack not yet scanned), not a block on invoicing.")
    print("Unit occupancy has been synced by the controller as each row "
          "inserted.")
    return {"created": made, "skipped": skipped, "charges": charge_rows,
            "aborted": False}
