"""Stage 6 — the portfolio history.

One row per building per period, carrying what was received, what the landlord
was paid, and what electricity and wifi cost. It is the record the spread is
read off, and the first stage whose output goes in front of the MD.

Nothing here touches the ledger. `Historical Monthly PL` is a reporting record
— ERPNext owns the GL, and the cash that produced these figures is loaded
later through the cutover control account. Loading history as journal entries
would post a year of vouchers against periods that are already closed.

**The periods are not all months.** Owner rent for August to October 2025 was
paid as one lump and the register never split it, so the first period is a
three-month one and carries `is_lump_period`. Everything from November 2025 is
monthly. Splitting the lump into three equal months would be an invention, and
it would put an owner-rent figure against August that no cheque supports.

**Three workbooks have to agree on what a building is called.** The revenue
sheet writes UG-180, the owner-rent register writes
`UMM GHUWAILINA-169/180` — with a non-breaking space in one of its two
spellings — and the expense sheet writes the ten Al Adekhar villas out
individually while the owner-rent register books them on a single
`TWAR-10 VILLAS` line. Those three disagreements are the whole reason 28
building-months looked like they carried revenue with no cost against them.
They did not. `_NAMES` is where the three vocabularies meet.

**Rent-free months are recorded, not zero-filled.** TV-20 has five, UG-169
three, TV-66 and TV-27 one each. The register names them explicitly. A
rent-free month is a real month with no owner rent, which is a different thing
from a month whose owner rent was never entered, and the difference moves the
headline spread by about 29,000.
"""

import frappe

from darkbrown.load import common as C

STAGE = "6"
SOURCE = "portfolio_history.csv"

LUMP = "Aug-Oct 2025"


def _money(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _resolve(rows):
    buildings = set(frappe.get_all("Building", pluck="name"))
    existing = set(frappe.get_all("Historical Monthly PL", pluck="name"))

    plan, problems, seen = [], [], {}
    for i, r in enumerate(rows, start=2):
        b = (r.get("building") or "").strip()
        label = (r.get("period_label") or "").strip()
        key = (b, label)

        def bad(column, value, rule, message):
            problems.append(C.Problem(SOURCE, i, column, value, rule, message))

        if key in seen:
            bad("period_label", label, "duplicate_in_file",
                "same building and period as row %d" % seen[key])
            continue
        seen[key] = i

        if b not in buildings:
            bad("building", b, "building_unresolved",
                "no Building on the site — stage 2 must be gated first")
        if not label:
            bad("period_label", label, "period_required",
                "the record is named from it")

        end = None
        try:
            end = frappe.utils.getdate(r.get("period_end"))
        except Exception:
            bad("period_end", r.get("period_end"), "period_end_unreadable",
                "not a date")

        figures = {}
        for col in ("rent_charged", "rent_received", "owner_rent", "kahrama",
                    "wifi"):
            v = _money(r.get(col))
            if v is None:
                bad(col, r.get(col), "not_a_number",
                    "could not be read as an amount")
                v = 0.0
            figures[col] = v

        # The profit in the file is what the workbook footed to. Recomputing it
        # and quietly using our own number would hide a disagreement rather
        # than report one, so it is compared instead.
        want = round(figures["rent_received"] - figures["owner_rent"]
                     - figures["kahrama"] - figures["wifi"], 2)
        got = _money(r.get("profit"))
        if got is not None and abs(got - want) > 0.5:
            bad("profit", got, "profit_does_not_foot",
                "received less costs comes to %.2f" % want)

        if figures["rent_received"] > 0 and figures["owner_rent"] <= 0 \
                and not (r.get("rent_free") or "").strip():
            bad("owner_rent", figures["owner_rent"], "revenue_without_cost",
                "rent taken with no landlord cost and no rent-free note")

        plan.append({"row": i, "building": b, "label": label, "end": end,
                     "lump": (r.get("is_lump_period") or "").strip() == "1",
                     "fig": figures, "profit": want, "raw": r,
                     "existing": ("HPL-%s-%s" % (label, b)) in existing})
    return plan, problems


def _totals(plan):
    t = {k: 0.0 for k in ("rent_charged", "rent_received", "owner_rent",
                          "kahrama", "wifi")}
    for p in plan:
        for k in t:
            t[k] += p["fig"][k]
    t["profit"] = sum(p["profit"] for p in plan)
    return t


def check():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    t = _totals(plan)
    fresh = [p for p in plan if not p["existing"]]
    free = [p for p in plan if (p["raw"].get("rent_free") or "").strip()]

    def q(v):
        return frappe.utils.fmt_money(v, currency="QAR")

    print("STAGE 6 CHECK — portfolio history")
    print("  %s: %d rows" % (SOURCE, len(rows)))
    print("  %d to create, %d already on the site"
          % (len(fresh), len(plan) - len(fresh)))
    print("  %d building(s) across %d period(s)"
          % (len({p["building"] for p in plan}),
             len({p["label"] for p in plan})))
    print("  rent charged   %s" % q(t["rent_charged"]))
    print("  rent received  %s   (%s uncollected)"
          % (q(t["rent_received"]), q(t["rent_charged"] - t["rent_received"])))
    print("  owner rent     %s" % q(t["owner_rent"]))
    print("  kahramaa %s, wifi %s" % (q(t["kahrama"]), q(t["wifi"])))
    print("  profit         %s" % q(t["profit"]))
    if free:
        kinds = {}
        for p in free:
            kinds.setdefault(p["raw"]["rent_free"], []).append(
                "%s %s" % (p["building"], p["label"]))
        print("  %d building-month(s) carry no owner rent, for two different "
              "reasons — they are not the same thing:" % len(free))
        for reason, where in sorted(kinds.items()):
            print("      %s" % reason)
            print("        %s" % ", ".join(where[:8]))
            if len(where) > 8:
                print("        ... and %d more" % (len(where) - 8))
    C.report(problems)
    if problems:
        print("  %d problem(s). Fix these before Run." % len(problems))
    return {"create": len(fresh), "problems": len(problems),
            "clean": not problems}


def run():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    if problems:
        C.report(problems)
        C.write_exceptions(STAGE, problems)
        frappe.throw("Stage 6 refused: %d problem(s). Run Check."
                     % len(problems))

    made, failed = 0, []
    print("STAGE 6 RUN — portfolio history")
    for p in plan:
        if p["existing"]:
            continue
        try:
            d = frappe.new_doc("Historical Monthly PL")
            d.building = p["building"]
            d.period_label = p["label"]
            d.period_end = p["end"]
            d.is_lump_period = 1 if p["lump"] else 0
            d.rent_received = p["fig"]["rent_received"]
            d.owner_rent = p["fig"]["owner_rent"]
            d.kahrama = p["fig"]["kahrama"]
            d.wifi = p["fig"]["wifi"]
            d.profit = p["profit"]
            d.flags.ignore_permissions = True
            d.insert()
            frappe.db.commit()
            made += 1
        except Exception as e:
            frappe.db.rollback()
            text = (str(e) or "").strip() or type(e).__name__
            failed.append(("%s %s" % (p["building"], p["label"]),
                           (text.splitlines() or ["?"])[0][:90]))

    if failed:
        C.report([C.Problem(SOURCE, "-", "building", n, "insert_failed", w)
                  for n, w in failed])
    print("  created %d period record(s)" % made)
    print("  Now press Gate.")
    return {"created": made, "failed": len(failed)}


def reload():
    print("STAGE 6 RELOAD — portfolio history")
    return run()


def gate():
    rows = C.rows(SOURCE)
    plan, problems = _resolve(rows)
    t = _totals(plan)

    on_site = frappe.db.count("Historical Monthly PL")
    site = frappe.get_all("Historical Monthly PL",
                          fields=["building", "period_label", "rent_received",
                                  "owner_rent", "kahrama", "wifi", "profit",
                                  "is_lump_period"])
    got = {k: round(sum(float(s.get(k) or 0) for s in site), 2)
           for k in ("rent_received", "owner_rent", "kahrama", "wifi",
                     "profit")}

    buildings = frappe.db.count("Building")
    covered = len({s["building"] for s in site})
    lumps = len([s for s in site if s.get("is_lump_period")])
    orphan = len([s for s in site
                  if not frappe.db.exists("Building", s["building"])])

    def money(a, b):
        return abs(round(a, 2) - round(b, 2)) < 1.0

    checks = [
        ("every period in the worksheet exists", on_site == len(plan),
         "%d on site vs %d expected" % (on_site, len(plan))),
        ("every building is covered", covered == buildings,
         "%d of %d building(s)" % (covered, buildings)),
        ("rent received reconciles",
         money(got["rent_received"], t["rent_received"]),
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(got["rent_received"], currency="QAR"),
            frappe.utils.fmt_money(t["rent_received"], currency="QAR"))),
        ("owner rent reconciles", money(got["owner_rent"], t["owner_rent"]),
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(got["owner_rent"], currency="QAR"),
            frappe.utils.fmt_money(t["owner_rent"], currency="QAR"))),
        ("profit reconciles", money(got["profit"], t["profit"]),
         "%s on site vs %s expected"
         % (frappe.utils.fmt_money(got["profit"], currency="QAR"),
            frappe.utils.fmt_money(t["profit"], currency="QAR"))),
        ("the lump period is marked", lumps == len(
            [p for p in plan if p["lump"]]),
         "%d row(s) flagged is_lump_period" % lumps),
        ("no record points at a building that is gone", not orphan,
         "%d orphan(s)" % orphan),
        ("the worksheet still resolves cleanly", not problems,
         "no unresolved rows" if not problems
         else "%d row(s) no longer resolve" % len(problems)),
    ]
    return C.gate_result(STAGE, checks)
