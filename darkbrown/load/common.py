"""Shared plumbing for the load stages.

One implementation of each thing, because the previous attempt had five copies
of `_norm` across five loaders and eight different shapes of problem report.
When a tenant matched in one stage and failed in another, there was no way to
tell which copy had diverged.
"""

import csv
import hashlib
import json
import os
import re

import frappe

DATA = os.path.join(os.path.dirname(__file__), "data")


# ----------------------------------------------------------------- normalise

def norm(value):
    """Fold a name for matching: case, punctuation and runs of space.

    The revenue worksheet holds 488 tenant names that collapse to 435 under
    this. "HAMED HRAIZ" and "Hamed Hraiz" are one person, and treating them as
    two is how the previous load ended up with 547 customers against 441
    tenancies.
    """
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def unit_key(value):
    """Fold a unit number so the same flat written two ways matches.

    The Tenancy Master writes 23 DAJ-21 and MQ-56 flats as F01, F02, F06 while
    the Revenue sheet writes them F-01, F-02, F-06. Without folding, those 23
    tenancies would find no unit and fail at Stage 5 — and the failure would
    read as "23 units missing" rather than "one sheet omits a hyphen".

    Deliberately narrow. An earlier version stripped every separator, which
    turned F-03/1 into F-31 — a real flat in TWR-20 and a different real flat
    that does not exist yet. Two homes, one record, and no way to notice.
    Only the missing hyphen is folded; slashes and letter suffixes are left
    exactly as written.
    """
    s = str(value or "").strip().upper()
    m = re.match(r"^([A-Z]+)-?(\d+)$", s)
    return "%s-%02d" % (m.group(1), int(m.group(2))) if m else s


# --------------------------------------------------------------- the problem

class Problem(object):
    """One rejected row, traceable back to the cell it came from.

    file / row / column are what let somebody open the worksheet next to the
    exceptions list and work down it. A bare count sends them guessing.
    """

    __slots__ = ("file", "row", "column", "value", "rule", "message")

    def __init__(self, file, row, column, value, rule, message):
        self.file, self.row, self.column = file, row, column
        self.value, self.rule, self.message = value, rule, message

    def as_dict(self):
        return {"file": self.file, "row": self.row, "column": self.column,
                "value": self.value, "rule": self.rule, "message": self.message}


def report(problems, limit=12):
    """Print grouped by rule, not one line per row.

    Stage 0 printed the same refusal 296 times and buried the three lines that
    mattered.
    """
    if not problems:
        return
    by_rule = {}
    for p in problems:
        by_rule.setdefault(p.rule, []).append(p)
    for rule, rows in sorted(by_rule.items()):
        head = rows[0]
        print("  ! %d x %s — %s" % (len(rows), rule, head.message))
        for p in rows[:3]:
            print("        row %s, %s = %r" % (p.row, p.column, p.value))
        if len(rows) > 3:
            print("        ... and %d more" % (len(rows) - 3))


def write_exceptions(stage, problems):
    """Also write them to a file, so the list outlives the log pane."""
    if not problems:
        return None
    path = frappe.get_site_path("private", "files",
                                "exceptions_stage_%s.csv" % stage)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=["file", "row", "column", "value",
                                               "rule", "message"])
            w.writeheader()
            for p in problems:
                w.writerow(p.as_dict())
        print("  exceptions written to %s" % path)
        return path
    except Exception as e:
        print("  ! could not write the exceptions file: %s" % e)
        return None


# ------------------------------------------------------------------- reading

def rows(filename):
    """Read a data file, verifying it against the manifest first.

    `opening_arrears.csv` shipped as a header row and nothing else in the
    previous attempt. The loader read it, found no rows, reported success, and
    the site went live with no opening arrears at all. A file that is
    unexpectedly empty is a failure, not a clean run — so the row count is
    checked before a single row is used.
    """
    path = os.path.join(DATA, filename)
    if not os.path.exists(path):
        frappe.throw("Data file missing: %s" % filename)

    raw = open(path, "rb").read()
    man = manifest().get(filename)
    if man:
        got = digest(raw)
        if got != man["sha256"]:
            frappe.throw("%s does not match the manifest (%s, expected %s). "
                         "Either the file or the manifest was edited alone."
                         % (filename, got, man["sha256"]))

    out = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if man and len(out) != man["rows"]:
        frappe.throw("%s holds %d rows, the manifest says %d."
                     % (filename, len(out), man["rows"]))
    if not out:
        frappe.throw("%s is empty. Refusing to report a clean load of nothing."
                     % filename)
    return out


def digest(raw):
    """Checksum the content, not the encoding.

    The first version hashed the bytes as read. Git on Windows commits CRLF as
    LF and the Linux server checks it out as LF, so a file that left here
    hashing fd01d278 arrived hashing 070c3584 without a character changing.
    The guard fired on the line endings and blocked a load that was correct.

    Normalising first means the checksum still catches a real edit — a changed
    figure, a dropped row, a renamed column — and stops caring about how the
    lines happen to end.
    """
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return hashlib.sha256(
        raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()[:16]


def manifest():
    path = os.path.join(DATA, "manifest.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


# ---------------------------------------------------------------- site facts

def company():
    name = frappe.db.get_single_value("DBR Settings", "default_company")
    if not name:
        name = frappe.db.get_value("Company", {}, "name")
    if not name:
        frappe.throw("No Company on the site. Stage 0 keeps it; if it is gone, "
                     "restore the backup.")
    return name


def gate_result(stage, checks):
    """A gate is a list of (label, ok, detail). Any false and the stage fails."""
    failed = [c for c in checks if not c[1]]
    print("STAGE %s GATE" % stage)
    for label, ok, detail in checks:
        print("  %-4s %-46s %s" % ("PASS" if ok else "FAIL", label, detail))
    if failed:
        print("  %d check(s) failed. The next stage must not run." % len(failed))
    else:
        print("  PASS — stage %s is complete." % stage)
    return {"pass": not failed,
            "checks": [{"label": c[0], "pass": c[1], "detail": c[2]}
                       for c in checks]}
