"""Static scanners for the harness.

These read what the code DOES, not what its comments say it used to do: each
file is tokenised and comments plus docstrings are dropped before matching, and
identifiers are matched on word boundaries so `_landlord_contracts()` does not
register as a use of the `landlord_contract` field.
"""
import glob
import os
import re
import tokenize

PHANTOM = ["cheque_number", "cleared_date", "bounce_date",
           "tenant_rental_agreement", "landlord_contract"]

# Files that legitimately own these names — a child doctype's own fieldnames,
# the AI extraction schema, the defensive fieldname resolver, and custom fields
# that belong to Purchase Invoice rather than Cheque.
OWNS = ("document_register_cheque", "doc_intake_prompts",
        "doc_intake.py", "setup_rent_invoicing")


def code_only(path):
    """[(lineno, text)] with comments and docstrings removed."""
    try:
        with open(path, "rb") as fh:
            toks = list(tokenize.tokenize(fh.readline))
    except Exception:
        return list(enumerate(open(path).read().split("\n"), 1))
    drop, prev = set(), None
    for t in toks:
        if t.type == tokenize.COMMENT:
            drop.update(range(t.start[0], t.end[0] + 1))
        elif t.type == tokenize.STRING and (
                prev is None or prev.type in (tokenize.INDENT, tokenize.DEDENT,
                                              tokenize.NEWLINE, tokenize.NL,
                                              tokenize.ENCODING)):
            drop.update(range(t.start[0], t.end[0] + 1))
        if t.type not in (tokenize.NL, tokenize.COMMENT):
            prev = t
    return [(i, l) for i, l in enumerate(open(path).read().split("\n"), 1)
            if i not in drop]


def _files(repo):
    return sorted(glob.glob(repo + "/darkbrown/**/*.py", recursive=True))


def phantom_fields(repo):
    bad = []
    for f in _files(repo):
        if any(o in f for o in OWNS):
            continue
        for i, line in code_only(f):
            for ph in PHANTOM:
                as_field = r"""(\.%s(?![A-Za-z0-9_])|["']%s["'])""" % (ph, ph)
                if re.search(as_field, line):
                    bad.append("%s:%d  %s"
                               % (os.path.basename(f), i, line.strip()[:70]))
    return bad


def bounced_status(repo):
    bad = []
    for f in _files(repo):
        for i, line in code_only(f):
            if '"Bounced"' not in line:
                continue
            if '"Returned": "Bounced"' in line:      # display label map
                continue
            bad.append("%s:%d  %s"
                       % (os.path.basename(f), i, line.strip()[:70]))
    return bad


GUARDED = re.compile(r"guard\(|has_permission|"
                     r"from darkbrown\.api import finance|"
                     r"from darkbrown\.api\.finance")


def endpoints(repo):
    """[(file, name, guarded, guest)] for every real whitelisted endpoint."""
    found = []
    for f in _files(repo):
        code = code_only(f)
        idx = {i: l for i, l in code}
        nums = sorted(idx)
        raw = open(f).read().split("\n")
        for pos, i in enumerate(nums):
            if not idx[i].strip().startswith("@frappe.whitelist"):
                continue
            j = pos + 1
            while j < len(nums) and not re.match(r"\s*def ", idx[nums[j]]):
                j += 1
            if j >= len(nums):
                continue
            name = re.match(r"\s*def\s+(\w+)", idx[nums[j]]).group(1)
            body = "\n".join(raw[nums[j] - 1: nums[j] + 44])
            found.append((os.path.basename(f), name,
                          bool(GUARDED.search(body)),
                          "allow_guest" in idx[i] and "True" in idx[i]))
    return found
