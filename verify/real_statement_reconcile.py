"""Synthetic accounting boundary checks; never loads customer statements."""

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stub_frappe  # noqa: F401
from darkbrown.api import statement_reconcile as subject


class Item(dict):
    __getattr__ = dict.get


class Source:
    is_private = 1
    file_name = "synthetic.pdf"
    file_url = "/private/files/synthetic.pdf"

    def __init__(self):
        self.attachments = []

    def get_content(self):
        return b"synthetic-pdf-bytes"

    def db_set(self, field, value, update_modified=False):
        self.attachments.append((field, value))


class Import:
    def __init__(self, data):
        self.data = data
        self.doctype = data["doctype"]
        self.name = "BSI-SYN"
        self.lines = []

    def append(self, field, row):
        assert field == "lines"
        self.lines.append(row)

    def insert(self):
        self.total_lines = len(self.lines)
        self.matched = sum(x["status"] == "Matched" for x in self.lines)
        self.unmatched = self.total_lines - self.matched


parsed = {"bank": "qnb", "pages": 1, "ocr_pages": [],
          "account_number": "1234-123456-789", "opening": "100.00",
          "closing": "110.00", "total_debit": "10.00", "total_credit": "20.00",
          "rows": [
              {"date": "2026-08-01", "value_date": None, "ref": "ABC123",
               "narrative": "Synthetic receipt", "amount": "20.00", "direction": "Credit",
               "balance": "120.00", "page": 1, "ocr_inferred": False},
              {"date": "2026-08-02", "value_date": None, "ref": "UNLINKED",
               "narrative": "Synthetic debit", "amount": "10.00", "direction": "Debit",
               "balance": "110.00", "page": 1, "ocr_inferred": False}]}

source = Source()
made = []


def get_all(kind, **kwargs):
    if kind == "Bank Account":
        return [Item(name="BANK-SYN", bank_account_no="1234123456789", account="GL-BANK")]
    if kind == "Bank Statement Import":
        return []
    if kind == "Payment Entry":
        return [Item(name="PE-SYN", reference_no="ABC123")]
    return []


def sql(query, args, as_dict=False):
    assert "`tabGL Entry`" in query
    return [Item(posting_date="2026-08-01", voucher_type="Payment Entry",
                 voucher_no="PE-SYN", signed="20.00")]


def new_import(data):
    doc = Import(data)
    made.append(doc)
    return doc


with patch.object(subject, "guard"), \
     patch.object(subject, "require_file_access", return_value=source), \
     patch.object(subject, "parse_statement", return_value=copy.deepcopy(parsed)), \
     patch.object(subject.frappe, "get_single", return_value=SimpleNamespace(default_company="SYN")), \
     patch.object(subject.frappe, "get_all", side_effect=get_all), \
     patch.object(subject.frappe.db, "sql", side_effect=sql), \
     patch.object(subject.frappe, "get_doc", side_effect=new_import):
    preview = subject.preview_real_statement(source.file_url)
    assert len(preview["rows"]) == 2
    assert (preview["matched"], preview["unmatched"]) == (1, 1)
    assert preview["rows"][0]["match"] == {"doctype": "Payment Entry", "name": "PE-SYN"}
    assert preview["rows"][1]["match"] is None
    result = subject.record_real_statement(source.file_url, preview["digest"])
    assert (result["total"], result["matched"], result["unmatched"]) == (2, 1, 1)
    assert len(made) == 1 and made[0].data["status"] == "Reviewed"
    assert made[0].lines[0]["matched_type"] == "Payment Entry"
    assert made[0].lines[1]["matched_type"] is None
    assert source.attachments == [("attached_to_doctype", "Bank Statement Import"),
                                  ("attached_to_name", "BSI-SYN")]

print("PASS complete statement, exact posted voucher, open exception, no posting")
