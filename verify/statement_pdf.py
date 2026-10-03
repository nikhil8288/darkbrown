"""Pure statement reader regressions; optional full private sample verification.

Usage: python verify/statement_pdf.py [QNB.pdf Doha.pdf]
The PDFs and their financial rows are never included in repository fixtures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from darkbrown.api.statement_pdf import _money, parse_statement, StatementError


def word(x, y, value):
    return (x, y, x + 10, y + 10, value, 0, 0, 0)


assert str(_money([word(719, 10, "50,000."), word(719, 20, "00")],
                  715, 759, "credit")) == "50000.00"
assert str(_money([word(761, 10, "-111,927."), word(761, 20, "50")],
                  759, 841, "balance")) == "-111927.50"
try:
    _money([word(719, 10, "100.00"), word(719, 20, "200.00")],
           715, 759, "credit")
except StatementError:
    pass
else:
    raise AssertionError("A second amount must be rejected")

if len(sys.argv) == 3:
    import fitz
    from collections import Counter

    for name, expected_bank, expected_pages, expected_rows in (
            (sys.argv[1], "qnb", 42, 224),
            (sys.argv[2], "doha", 5, 97)):
        data = Path(name).read_bytes()
        result = parse_statement(data)
        assert (result["bank"], result["pages"], len(result["rows"])) == (
            expected_bank, expected_pages, expected_rows)
        keys = Counter((r["date"], r["ref"], r["amount"], r["direction"])
                       for r in result["rows"])
        assert sum(n - 1 for n in keys.values() if n > 1) == (
            10 if expected_bank == "qnb" else 1)
        assert all(r["date"] < "2026-10-01" for r in result["rows"])
        pdf = fitz.open(stream=data, filetype="pdf")
        pdf.delete_page(1)
        try:
            parse_statement(pdf.tobytes())
        except StatementError:
            pass
        else:
            raise AssertionError("Removing a page must fail validation")
        print(f"{expected_bank}: {expected_pages} pages, {expected_rows} rows, balance and coverage verified")
else:
    assert len(sys.argv) == 1, "Pass QNB PDF then Doha Bank PDF"
    print("Synthetic amount checks passed; supply private PDFs for full coverage")
