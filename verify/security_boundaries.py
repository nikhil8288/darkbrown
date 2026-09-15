"""Fast synthetic checks for DB-01/02/03/20 repairs.

These are source/stub tests. Staging Frappe evidence is intentionally separate.
"""

import json
import os
import sys
import glob
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_frappe as S
sys.path.insert(0, os.path.join(HERE, ".."))

for path in glob.glob(os.path.join(HERE, "..", "darkbrown", "darkbrown",
                                   "doctype", "*", "*.json")):
    spec = json.load(open(path, encoding="utf-8"))
    if spec.get("doctype") == "DocType":
        S.SCHEMA[spec["name"]] = {
            field["fieldname"]: (field["fieldtype"], field.get("options"),
                                  field.get("default"))
            for field in spec.get("fields", [])}

from darkbrown import permissions, renderer
from darkbrown.api import app, doc_intake, operations

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)


def reset(role="General Manager"):
    S.CALLS.clear()
    S.SESSION["user"] = "scoped@example.invalid"
    S.frappe.session.user = S.SESSION["user"]
    S.SESSION["roles"] = [role]
    S.DB.clear()
    S.DB.update({
        "User Permission": [{"name": "UP-1", "user": S.SESSION["user"],
                             "allow": "Building", "for_value": "SYN-A"}],
        "Building": [{"name": "SYN-A"}, {"name": "SYN-B"}],
        "Unit": [{"name": "SYN-A-A-01", "building": "SYN-A", "status": "Vacant"},
                 {"name": "SYN-B-B-01", "building": "SYN-B", "status": "Vacant"}],
        "Tenancy Agreement": [
            {"name": "SYN-TA-A", "building": "SYN-A", "unit": "SYN-A-A-01",
             "tenant": "SYN-TENANT-A"},
            {"name": "SYN-TA-B", "building": "SYN-B", "unit": "SYN-B-B-01",
             "tenant": "SYN-TENANT-B"},
        ],
        "Maintenance Request": [
            {"name": "SYN-JOB-A", "building": "SYN-A", "status": "Open",
             "cost_lines": [], "over_ceiling": 0},
            {"name": "SYN-JOB-B", "building": "SYN-B", "status": "Open",
             "cost_lines": [], "over_ceiling": 0},
        ],
        "Document Register": [], "Document Archive": [], "File": [],
    })


def expect_denied(fn):
    try:
        fn()
    except S.PermissionError_:
        return
    raise AssertionError("request was not denied")


def t_role_field_matrix():
    for role, allowed, forbidden in (
        ("Maintenance", {"buildings", "units", "jobs"}, {"tenants", "landlords", "bankAccounts"}),
        ("Documentation", {"buildings", "units", "tenants", "agreements", "docs"}, {"landlords", "bankAccounts", "staff"}),
        ("Accounts", {"invoices", "cheques", "bankAccounts"}, {"jobs", "staff", "docs"}),
        ("General Manager", {"jobs", "tenants", "approvals"}, {"bankAccounts", "staff", "petty"}),
    ):
        reset(role)
        got = app._allowed_sections()
        assert allowed <= got and not (forbidden & got), (role, got)
    reset("Managing Director")
    assert app._allowed_sections() is None
    reset("General Manager")
    filtered = app._filter_section_fields("landlords", [{
        "id": "SYN-LL-A", "n": "Synthetic Landlord Alpha LLC",
        "bank": "SYN-IBAN", "idno": "SYN-ID", "phone": "+000", "email": "x@example.invalid"}])
    assert filtered == [{"id": "SYN-LL-A", "n": "Synthetic Landlord Alpha LLC"}]


def t_scoped_lists_and_totals():
    reset()
    rows = [{"id": "SYN-A", "value": 10}, {"id": "SYN-B", "value": 999}]
    got = app._scope_section("buildings", rows)
    assert got == [{"id": "SYN-A", "value": 10}], got
    assert sum(r["value"] for r in got) == 10


def t_cross_building_write_denied():
    reset("Maintenance")
    expect_denied(lambda: operations.advance_job("SYN-JOB-B", "Assigned"))
    assert not any(call[0] in ("save", "db.set_value") for call in S.CALLS)
    result = operations.advance_job("SYN-JOB-A", "Assigned")
    assert result["status"] == "Assigned"
    assert any(call[0] == "save" for call in S.CALLS)


def t_file_denied_before_bytes():
    reset("Documentation")
    read_count = {"n": 0}
    def content():
        read_count["n"] += 1
        return b"not-real-private-content"
    S.DB["File"] = [{"name": "FILE-DENIED", "file_url": "/private/files/denied.png",
                     "file_name": "denied.png", "_deny_read": True,
                     "_content_hook": content}]
    expect_denied(lambda: doc_intake._file_to_blocks("/private/files/denied.png"))
    assert read_count["n"] == 0


def t_authorized_file_still_reads():
    reset("Documentation")
    read_count = {"n": 0}
    def content():
        read_count["n"] += 1
        return b"synthetic-image-bytes"
    S.DB["File"] = [{"name": "FILE-OK", "file_url": "/private/files/ok.png",
                     "file_name": "ok.png", "content": b"synthetic-image-bytes",
                     "_content_hook": content}]
    blocks, pages = doc_intake._file_to_blocks("/private/files/ok.png")
    assert pages == 1 and blocks[0]["type"] == "image" and read_count["n"] == 1


def t_ocr_denied_server_side():
    reset("Documentation")
    expect_denied(lambda: doc_intake.extract_from_upload("/private/files/any.png"))
    assert not S.CALLS


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(); self.scripts = 0
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script": self.scripts += 1


def t_boot_json_cannot_close_script():
    marker = "</script><script>inert-audit-marker</script>"
    encoded = renderer._script_json({"name": marker, "line": "\u2028"})
    html = "<script>window.x=" + encoded + ";</script>"
    parser = _Scripts(); parser.feed(html)
    assert parser.scripts == 1
    assert html.lower().count("</script>") == 1
    assert "\\u003c/script\\u003e" in encoded


def t_intake_template_escapes_stored_text_and_hides_ocr():
    source = open(os.path.join(HERE, "..", "darkbrown", "www", "doc-intake.html"),
                  encoding="utf-8").read()
    assert "function esc(value)" in source
    assert "${esc(doc.extraction_notes)}" in source
    assert 'id="file_input"' in source and "multiple disabled" in source
    shell = open(os.path.join(HERE, "..", "darkbrown", "shell", "index.html"),
                 encoding="utf-8").read()
    assert "window.DB_OCR_ENABLED" in shell
    assert 'data-r="intake" style="display:none"' in shell


for name, fn in (
    ("role/field matrix", t_role_field_matrix),
    ("scoped list and total", t_scoped_lists_and_totals),
    ("cross-building write denial and authorized write", t_cross_building_write_denied),
    ("private file denial before bytes", t_file_denied_before_bytes),
    ("authorized private-file read", t_authorized_file_still_reads),
    ("OCR server denial", t_ocr_denied_server_side),
    ("HTML-safe boot serialization", t_boot_json_cannot_close_script),
    ("inert stored text and OCR interface", t_intake_template_escapes_stored_text_and_hides_ocr),
):
    check(name, fn)

print("security boundary checks: %d passed" % len(PASS))
for name in PASS:
    print("  PASS", name)
