"""Synthetic, read-only API boundary checks for bank PDF validation."""

import sys
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stub_frappe  # noqa: F401; supplies a Frappe boundary without a bench
from darkbrown.api import cashdesk
from darkbrown.api import statement_pdf
from darkbrown import permissions


class PrivateFile:
    is_private = 1
    file_name = "synthetic.pdf"

    def get_content(self):
        return b"synthetic"


file = PrivateFile()
parsed = {"bank": "qnb", "pages": 2, "rows": [
    {"date": "2026-09-30", "ref": "", "amount": "10.00", "direction": "Credit"},
    {"date": "2026-10-01", "ref": "", "amount": "10.00", "direction": "Debit"}],
    "opening": "0.00", "closing": "0.00", "total_debit": "10.00",
    "total_credit": "10.00", "account_number": "SYN-1234"}

with patch.object(cashdesk, "guard"), \
     patch.object(permissions, "require_file_access", return_value=file), \
     patch.object(statement_pdf, "parse_statement", return_value=copy.deepcopy(parsed)), \
     patch.object(cashdesk.frappe, "get_single", return_value=SimpleNamespace(default_company="SYN")), \
     patch.object(cashdesk.frappe, "get_all", side_effect=lambda dt, **kw:
                  [SimpleNamespace(name="BANK-SYN", bank_account_no="SYN1234")]
                  if dt == "Bank Account" else []):
    result = cashdesk.preview_statement_file("/private/files/synthetic.pdf")
    assert result["bank_account"] == "BANK-SYN"
    assert (result["historical"], result["eligible"]) == (1, 1)
    assert result["rows"] == parsed["rows"]
    assert result["account_suffix"] == "1234"

with patch.object(cashdesk, "guard"), \
     patch.object(permissions, "require_file_access", return_value=file), \
     patch.object(statement_pdf, "parse_statement", return_value=copy.deepcopy(parsed)), \
     patch.object(cashdesk.frappe, "get_single", return_value=SimpleNamespace(default_company="SYN")), \
     patch.object(cashdesk.frappe, "get_all", side_effect=lambda dt, **kw:
                  [SimpleNamespace(name="BANK-SYN", bank_account_no="SYN1234")]
                  if dt == "Bank Account" else ["BSI-SYN"]
                  if dt == "Bank Statement Import" else
                  [SimpleNamespace(txn_date="2026-10-01", bank_ref="",
                                   amount=10, direction="Debit")]):
    result = cashdesk.preview_statement_file("/private/files/synthetic.pdf")
    assert result["overlap_candidates"] == 1
    assert any("overlap" in message for message in result["exceptions"])

with patch.object(cashdesk, "guard", side_effect=PermissionError), \
     patch.object(permissions, "require_file_access") as read:
    try:
        cashdesk.preview_statement_file("/private/files/synthetic.pdf")
    except PermissionError:
        pass
    else:
        raise AssertionError("Role denial must stop before file access")
    read.assert_not_called()

file.is_private = 0
with patch.object(cashdesk, "guard"), \
     patch.object(permissions, "require_file_access", return_value=file), \
     patch.object(statement_pdf, "parse_statement") as parse:
    try:
        cashdesk.preview_statement_file("/files/public.pdf")
    except Exception:
        pass
    else:
        raise AssertionError("Public bank statement must be rejected")
    parse.assert_not_called()

print("PASS private file, role ordering, account mapping and historical cutoff")
