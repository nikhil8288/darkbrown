"""One-shot seed of owner-rent cheques payable as Cheque records
(direction = Outgoing). Feeds the MD dashboard "Upcoming Landlord PDC"
alert and chart C2.

    STEP 1  bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.dry_run
    STEP 2  map any unmatched names in pdc_name_map.csv (and, optionally,
            property codes in pdc_building_map.csv), re-run dry_run
    STEP 3  bench --site erp.darkbrown.qa execute darkbrown.patches.seed_pdc_outgoing.run

MATCHING (A-3)
    Exact normalised name only, plus a human-curated pdc_name_map.csv for the
    residue. The old token-overlap fallback matched on two shared name parts,
    which against this landlord base posts one owner's cheque under another
    owner's name. run() ABORTS while any row is unmatched and never invents a
    Supplier.

IDEMPOTENCY (A-4)
    The old key was (party, cheque_date, amount), which silently COLLAPSED
    genuine duplicates — pdc_outgoing.csv currently contains two distinct
    QAR 14,000 cheques to Ali Mubarak Y A Al-Kuwari dated 2026-07-13, and only
    one of them was ever created. Matching is now by multiplicity: the number
    of cheques the CSV asks for in each (party, date, amount) group is compared
    with the number that already exist, and only the shortfall is created. That
    is duplicate-safe and survives Accounts editing cheque_no afterwards.

CHEQUE NUMBERS
    The source sheet carries no cheque numbers, so each row gets a stable
    placeholder derived from its CSV row: PDC-SEED-001. The old "TBC-<n>"
    counter restarted every run and re-issued numbers already in the register.
    Replace these in the desk as the real numbers come in.

This module is deliberately NOT a Frappe patch. It is bench-execute only, so
that a migrate can never write to the cheque register as a side effect.
"""
import collections
import csv
import os
import re

import frappe

CSV = os.path.join(os.path.dirname(__file__), "pdc_outgoing.csv")
NAME_MAP = os.path.join(os.path.dirname(__file__), "pdc_name_map.csv")
BUILDING_MAP = os.path.join(os.path.dirname(__file__), "pdc_building_map.csv")

EXPECTED_TOTAL = 538000.00


def _norm(s):
    s = (s or "").upper().replace("\xa0", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return " ".join(s.split())


def _supplier_index():
    idx = {}
    for s in frappe.get_all("Supplier", fields=["name", "supplier_name"]):
        idx.setdefault(_norm(s.supplier_name), []).append(s.name)
    return idx


def _sidecar(path, key_col, val_col):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            k = _norm(row.get(key_col))
            v = (row.get(val_col) or "").strip()
            if k and v:
                out[k] = v
    return out


def _match(party, idx, overrides):
    n = _norm(party)
    if n in overrides:
        sup = overrides[n]
        if not frappe.db.exists("Supplier", sup):
            return None, "map-target-missing"
        return sup, "mapped"
    hit = idx.get(n)
    if not hit:
        return None, "unmatched"
    if len(hit) > 1:
        return None, "ambiguous"
    return hit[0], "exact"


def _building_for(code, bmap):
    """Resolve a source property_code to a Building.

    Deliberately conservative. The property codes in this sheet are not the
    canonical building names (UG-169/180 covers two, TWAR -10 VILLAS is a
    group), and that reconciliation is still an open question. An exact
    Building name match or an explicit line in pdc_building_map.csv resolves;
    anything else leaves building blank rather than guessing, which is a
    reportable gap instead of a wrong cost centre.
    """
    n = _norm(code)
    if n in bmap:
        b = bmap[n]
        return b if frappe.db.exists("Building", b) else None
    if frappe.db.exists("Building", code):
        return code
    return None


def _rows():
    with open(CSV) as f:
        return list(csv.DictReader(f))


def _key(sup, r):
    return (sup, str(r["cheque_date"]), round(float(r["amount"]), 2))


def _existing_counts(keys):
    """How many cheques already exist for each (party, date, amount) group."""
    counts = collections.Counter()
    for sup, date, amt in set(keys):
        counts[(sup, date, amt)] = frappe.db.count("Cheque", {
            "party": sup,
            "party_type": "Supplier",
            "direction": "Outgoing",
            "cheque_date": date,
            "amount": amt,
        })
    return counts


# ---------------------------------------------------------------- commands

def dry_run():
    rows = _rows()
    idx = _supplier_index()
    overrides = _sidecar(NAME_MAP, "party", "supplier")
    bmap = _sidecar(BUILDING_MAP, "property_code", "building")

    print("=" * 76)
    print("DRY RUN - nothing created")
    bad, nobuilding = [], []
    resolved = []
    for i, r in enumerate(rows):
        sup, how = _match(r["party"], idx, overrides)
        bld = _building_for(r["property_code"], bmap) if sup else None
        if not sup:
            bad.append((i, r, how))
        elif not bld:
            nobuilding.append((i, r))
        resolved.append((i, r, sup, how, bld))
        print("%s [%-9s] %s  %-34s QAR %9s -> %-18s %s"
              % ("OK " if sup else "?? ", how, r["cheque_date"],
                 r["party"][:34], format(float(r["amount"]), ",.0f"),
                 sup or "NO SUPPLIER MATCH", bld or "(no building)"))

    counts = _existing_counts([_key(s, r) for _, r, s, _, _ in resolved if s])
    dupes = collections.Counter(
        _key(s, r) for _, r, s, _, _ in resolved if s)
    to_make = sum(max(0, want - counts[k]) for k, want in dupes.items())

    print("-" * 76)
    print("rows: %d  unmatched: %d  without building: %d  would create: %d"
          % (len(rows), len(bad), len(nobuilding), to_make))
    total = sum(float(r["amount"]) for r in rows)
    print("total: QAR %s (expected %s)"
          % (format(total, ",.0f"), format(EXPECTED_TOTAL, ",.0f")))
    if abs(total - EXPECTED_TOTAL) > 0.005:
        print("*** CSV TOTAL DOES NOT MATCH THE EXPECTED FIGURE ***")
    if bad:
        print()
        print("UNMATCHED - run() WILL ABORT. Add a line per name to")
        print("pdc_name_map.csv:")
        print()
        print("party,supplier")
        for i, r, how in bad:
            print('"%s",          # row %d  (%s)' % (r["party"], i + 2, how))
    if nobuilding:
        print()
        print("NO BUILDING - these will be created with building blank, which")
        print("keeps them out of per-building reporting. Map the codes in")
        print("pdc_building_map.csv when the building register is settled:")
        print()
        print("property_code,building")
        for i, r in nobuilding:
            print('"%s",' % r["property_code"])
    return {"rows": len(rows), "unmatched": len(bad),
            "no_building": len(nobuilding), "to_create": to_make}


def run():
    rows = _rows()
    idx = _supplier_index()
    overrides = _sidecar(NAME_MAP, "party", "supplier")
    bmap = _sidecar(BUILDING_MAP, "property_code", "building")

    resolved = []
    unmatched = 0
    for i, r in enumerate(rows):
        sup, how = _match(r["party"], idx, overrides)
        if not sup:
            unmatched += 1
        resolved.append((i, r, sup, _building_for(r["property_code"], bmap)
                         if sup else None))

    if unmatched:
        print("ABORTING: %d unmatched landlord names." % unmatched)
        print("Nothing was created. Run dry_run for the list, then map each")
        print("one in pdc_name_map.csv. This seeder never auto-creates a")
        print("Supplier - a phantom landlord is worse than a stopped run.")
        return {"created": 0, "skipped": 0, "aborted": True}

    total = sum(float(r["amount"]) for r in rows)
    if abs(total - EXPECTED_TOTAL) > 0.005:
        print("ABORTING: CSV total QAR %s does not match the expected %s."
              % (format(total, ",.0f"), format(EXPECTED_TOTAL, ",.0f")))
        return {"created": 0, "skipped": 0, "aborted": True}

    counts = _existing_counts([_key(s, r) for _, r, s, _ in resolved])
    consumed = collections.Counter()
    made = skipped = 0

    for i, r, sup, bld in resolved:
        k = _key(sup, r)
        # Skip only as many rows in this group as already exist. Everything
        # beyond that is a genuine additional cheque, not a duplicate.
        if consumed[k] < counts[k]:
            consumed[k] += 1
            skipped += 1
            continue
        consumed[k] += 1

        doc = frappe.new_doc("Cheque")
        payload = {
            # V2 Cheque takes Incoming/Outgoing, not the V1 prose value; the
            # field is cheque_no, not cheque_number; and there is no "Pending"
            # status. A landlord cheque written but not yet cleared is
            # "Received" - the only one of the seven that means "in hand,
            # nothing done with it yet".
            "direction": "Outgoing",
            "party_type": "Supplier",
            "party": sup,
            "cheque_date": r["cheque_date"],
            "amount": round(float(r["amount"]), 2),
            "cheque_no": "PDC-SEED-%03d" % (i + 1),
            "status": "Received",
        }
        if bld:
            payload["building"] = bld
        doc.update(payload)
        doc.flags.ignore_permissions = True
        doc.insert()
        made += 1

    frappe.db.commit()
    print("created %d PDC cheques, skipped %d already present" % (made, skipped))
    blank = sum(1 for _, _, _, b in resolved if not b)
    if blank:
        print("NOTE: %d of these carry no building link. They will not appear "
              "in per-building reporting until pdc_building_map.csv is "
              "completed and the records are updated." % blank)
    return {"created": made, "skipped": skipped, "aborted": False}
