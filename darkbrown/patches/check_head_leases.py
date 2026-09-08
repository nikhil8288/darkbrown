"""What the Head Lease records actually say, and which of it is real.

    bench --site erp.darkbrown.qa execute darkbrown.patches.check_head_leases.report

WHY THIS EXISTS

The MD building table showed all 22 buildings ending on the same day,
31 Jul 2027. Head leases signed with 22 different landlords do not expire
together, so that date is a placeholder somebody typed once.

It is not cosmetic. `api.number_cards._expiring("Head Lease", "end_date", 90)`
and the "expiring in 90 days" filter on the buildings screen are both driven
by `end_date`. A placeholder means the renewal alerts for the single largest
cost line in the business are keyed to a date nobody chose.

Worse, it cannot be regenerated. `buildings_payload.json` carries no
`head_lease` block at all, and `portfolio.onboard_building` only creates a
Head Lease when `annual_rent` and `start_date` are both present - so the
loaders in this repo create none. Whatever made these records is not in
version control, and rebuilding the site from the repo would produce a
portfolio with no head leases whatsoever.

This only reports. Nothing here invents a date: the real ones are on the
signed head lease contracts and have to be entered from them.

WHAT TO DO WITH THE OUTPUT

Take the `NEEDS A REAL DATE` list to the head lease files, put the true
start and end on each Head Lease, then re-run this until it prints clean.
Add a `head_lease` block to `buildings_payload.json` at the same time so the
portfolio survives a rebuild.
"""
import collections

import frappe

from darkbrown.patches import _ledger_common as L


def _company():
    return L.company()


def report():
    company = _company()
    leases = frappe.get_all(
        "Head Lease",
        fields=["name", "building", "landlord", "status", "start_date",
                "end_date", "monthly_rent", "annual_rent"],
        order_by="building asc")

    buildings = frappe.get_all("Building", fields=["name", "building_name"],
                               order_by="building_name asc")

    print("=" * 78)
    print("HEAD LEASE AUDIT   company: %s" % company)
    print("=" * 78)

    if not leases:
        print("")
        print("No Head Lease records at all. Every building margin is revenue")
        print("with no cost against it, and the MD table is meaningless.")
        return {"leases": [], "suspect": [], "missing": [b.name for b in buildings]}

    have = {l.building for l in leases}
    missing = [b for b in buildings if b.name not in have]

    # A date shared by more than a couple of buildings was not read off a
    # contract. Two buildings genuinely signed on the same day is plausible;
    # eleven is not.
    ends = collections.Counter(str(l.end_date) for l in leases if l.end_date)
    starts = collections.Counter(str(l.start_date) for l in leases if l.start_date)
    suspect_end = {d for d, n in ends.items() if n >= 3}
    suspect_start = {d for d, n in starts.items() if n >= 3}

    print("")
    print("  %-10s %-28s %-12s %-12s %12s" %
          ("BUILDING", "LANDLORD", "START", "END", "MONTHLY"))
    bad = []
    for l in leases:
        flag = ""
        if not l.end_date or str(l.end_date) in suspect_end:
            flag = "  <-- date not credible"
        elif not l.start_date or str(l.start_date) in suspect_start:
            flag = "  <-- start not credible"
        if flag:
            bad.append(l)
        print("  %-10s %-28s %-12s %-12s %12s%s"
              % (str(l.building)[:10], str(l.landlord or "-")[:28],
                 l.start_date or "-", l.end_date or "-",
                 format(float(l.monthly_rent or 0), ",.0f"), flag))

    print("")
    for d, n in sorted(ends.items(), key=lambda x: -x[1]):
        if n >= 3:
            print("  %d head leases all end on %s. That is a placeholder, "
                  "not %d contracts." % (n, d, n))

    if bad:
        print("")
        print("NEEDS A REAL DATE - %d lease(s):" % len(bad))
        for l in bad:
            print("   %-10s %s" % (str(l.building)[:10], l.name))
        print("")
        print("Until these are corrected, the 90-day head lease renewal alert")
        print("and the buildings-screen expiry filter are both unreliable.")

    if missing:
        print("")
        print("NO HEAD LEASE RECORD - %d building(s):" % len(missing))
        for b in missing:
            print("   %-10s %s" % (str(b.name)[:10], b.building_name or ""))
        print("   These show full revenue against zero cost.")

    if not bad and not missing:
        print("")
        print("Every building has a head lease and no date looks placeheld.")

    return {"leases": leases, "suspect": [l.name for l in bad],
            "missing": [b.name for b in missing]}
