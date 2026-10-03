"""Read the two supported digital bank statement layouts without posting money.

This module deliberately fails closed: the caller receives no importable rows
unless every detected transaction and the entire running balance validate.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import fitz


class StatementError(ValueError):
    pass


DATE_QNB = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
DATE_DOHA = re.compile(r"\d{2}-\d{2}-\d{4}\Z")
MONEY = re.compile(r"-?\d[\d,]*\.\d{2}\Z")


def _money(words, left, right, label):
    tokens = [w for w in words if left <= w[0] < right]
    if not tokens:
        return None
    # Doha Bank may put the two decimal places on the following printed line.
    value = tokens[0][4]
    if value.endswith(".") and len(tokens) > 1:
        value += tokens[1][4]
    if len(tokens) > (2 if tokens[0][4].endswith(".") else 1):
        raise StatementError(f"More than one {label} amount in a transaction")
    if not MONEY.fullmatch(value):
        raise StatementError(f"Unreadable {label} amount")
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise StatementError(f"Unreadable {label} amount") from exc


def _date(value, fmt):
    try:
        return datetime.strptime(value, fmt).date().isoformat()
    except ValueError as exc:
        raise StatementError("Invalid transaction date") from exc


def _row(words, kind, page, ocr=False):
    start = words[0]
    def amount(left, right, label):
        try:
            return _money(words, left, right, label)
        except StatementError:
            if ocr and label != "balance":
                return None
            raise
    if kind == "qnb":
        debit = amount(290, 375, "debit")
        credit = amount(375, 470, "credit")
        balance = amount(470, 590, "balance")
        date = _date(start[4], "%d/%m/%Y")
        narrative = " ".join(w[4] for w in words if 90 <= w[0] < 290)
        ref = next((w[4] for w in words if 90 <= w[0] < 290
                    and re.search(r"\d{5,}", w[4])), "")
        value_date = None
    else:
        debit = amount(670, 715, "debit")
        credit = amount(715, 759, "credit")
        balance = amount(759, 841, "balance")
        date = _date(start[4], "%d-%m-%Y")
        refs = [w[4] for w in words if 115 <= w[0] < 180 and abs(w[1] - start[1]) < 4]
        ref = refs[0] if refs else ""
        narrative = " ".join(w[4] for w in words if 180 <= w[0] < 620)
        dates = [w[4] for w in words if 620 <= w[0] < 670 and DATE_DOHA.fullmatch(w[4])]
        value_date = _date(dates[0], "%d-%m-%Y") if dates else None
    inferred = ocr and debit is None and credit is None and balance is not None
    if ((debit is None) == (credit is None) and not inferred) or balance is None:
        raise StatementError(f"Page {page}: transaction needs exactly one debit or credit and a balance")
    if (credit is not None and credit <= 0) or (debit is not None and debit == 0):
        raise StatementError(f"Page {page}: invalid signed amount")
    signed = None if inferred else credit if credit is not None else -abs(debit)
    if signed == 0:
        raise StatementError(f"Page {page}: zero transaction amount")
    return {"date": date, "value_date": value_date, "ref": ref,
            "narrative": narrative.strip(), "amount": abs(signed) if signed is not None else None,
            "direction": "Credit" if signed and signed > 0 else "Debit" if signed else None,
            "balance": balance, "page": page, "ocr_inferred": inferred}


def parse_statement(data):
    """Return validated rows and provenance for a QNB or Doha Bank PDF.

    Scanned pages use local OCR and must satisfy the same arithmetic and page
    checks as text PDFs; an uncertain scan is rejected, never guessed.
    Decimal values are returned as strings so API clients cannot round them.
    """
    if not data or len(data) > 20 * 1024 * 1024:
        raise StatementError("PDF is empty or exceeds the 20 MB limit")
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise StatementError("Cannot open this PDF") from exc
    try:
        if pdf.is_encrypted or not 1 <= len(pdf) <= 200:
            raise StatementError("PDF is encrypted or has an unsupported page count")
        def page_content(page):
            native = page.get_text()
            if len(native.strip()) >= 100:
                return native, page.get_text("words", sort=True), False
            try:
                textpage = page.get_textpage_ocr(dpi=300, full=True)
                return (page.get_text(textpage=textpage),
                        page.get_text("words", textpage=textpage, sort=True), True)
            except Exception as exc:
                raise StatementError("Scanned page needs local OCR support and review") from exc

        first, first_words, first_ocr = page_content(pdf[0])
        kind = ("qnb" if "Qatar National Bank" in first and "ACCOUNT SUMMARY" in first
                else "doha" if "Doha Bank" in first and "Datewise Account Transactions" in first
                else None)
        if not kind:
            raise StatementError("Unknown bank statement layout or scanned PDF; review required")
        rows, current, headings, ocr_pages, seen_markers = [], [], [], [], 0
        for page_index, page in enumerate(pdf):
            page_no = page_index + 1
            text, words, was_ocr = (first, first_words, first_ocr) if page_index == 0 else page_content(page)
            if was_ocr:
                ocr_pages.append(page_no)
            if len(text.strip()) < 100:
                raise StatementError(f"Page {page_no} has no readable text; OCR review required")
            if kind == "qnb" and "Bank Statement" not in text:
                raise StatementError(f"Page {page_no} is not a QNB statement page")
            if kind == "doha" and not re.search(r"Copyright\s+\d{4}.*Doha Bank", text):
                raise StatementError(f"Page {page_no} is not a Doha statement page")
            page_marker = (re.search(r"Page\s+(\d+)\s+of\s+(\d+)", text)
                           if kind == "qnb" else
                           re.search(r"(\d+)\s*(?:of|0f)\s*(\d+)\s*\Z", text.strip(), re.I))
            if page_marker and (int(page_marker[1]), int(page_marker[2])) != (page_no, len(pdf)):
                raise StatementError(f"Page {page_no}: page numbering or total pages disagree")
            if page_marker:
                seen_markers += 1
            elif not was_ocr:
                raise StatementError(f"Page {page_no}: page numbering is unreadable")
            date_pattern = DATE_QNB if kind == "qnb" else DATE_DOHA
            left = 37 if kind == "qnb" else 44
            for word in words:
                x, y, _, _, value, *_ = word
                if abs(x - left) < 3 and date_pattern.fullmatch(value):
                    if current:
                        rows.append(_row(current, kind, headings[-1], headings[-1] in ocr_pages))
                    current = [word]
                    headings.append(page_no)
                elif current and ((kind == "qnb" and 170 <= y < 695) or
                                  (kind == "doha" and 70 <= y < 550)):
                    if kind == "qnb" and ("CLOSING BALANCE" in text and
                            y >= next((w[1] for w in words if w[4] == "CLOSING"), 999)):
                        continue
                    if kind == "doha" and value in ("Transaction", "Document", "Description", "Value", "Debit", "Credit", "Balance", "Date", "#") and y < 70:
                        continue
                    current.append(word)
            if kind == "qnb" and "CLOSING BALANCE" in text and current:
                rows.append(_row(current, kind, headings[-1], headings[-1] in ocr_pages))
                current = []
        if current:
            rows.append(_row(current, kind, headings[-1], headings[-1] in ocr_pages))
        if not seen_markers:
            raise StatementError("No readable printed page total in scanned statement")
        if not rows:
            raise StatementError("No transactions found")
        if any(rows[i]["date"] > rows[i + 1]["date"] for i in range(len(rows) - 1)):
            raise StatementError("Transactions are out of date order")

        if kind == "qnb":
            summary = first.split("ACCOUNT SUMMARY", 1)[1].split("OPENING BALANCE", 1)[0]
            amounts = re.findall(r"(?<!\d)-?\d[\d,]*\.\d{2}\b", summary)
            if len(amounts) < 4:
                raise StatementError("QNB account summary is unreadable")
            total_debit, total_credit, opening, closing = (
                Decimal(s.replace(",", "")) for s in amounts[:4])
        else:
            if rows[0]["amount"] is None:
                raise StatementError("First Doha transaction amount needs visual review")
            total_debit = sum((r["amount"] for r in rows if r["direction"] == "Debit"), Decimal(0))
            total_credit = sum((r["amount"] for r in rows if r["direction"] == "Credit"), Decimal(0))
            opening = rows[0]["balance"] - (rows[0]["amount"] if rows[0]["direction"] == "Credit" else -rows[0]["amount"])
            closing = rows[-1]["balance"]
        running = opening
        for index, row in enumerate(rows, 1):
            if row["amount"] is None:
                signed = row["balance"] - running
                if signed == 0:
                    raise StatementError(f"Page {row['page']}, transaction {index}: OCR amount is missing")
                row["amount"] = abs(signed)
                row["direction"] = "Credit" if signed > 0 else "Debit"
            running += row["amount"] if row["direction"] == "Credit" else -row["amount"]
            if running != row["balance"]:
                raise StatementError(f"Page {row['page']}, transaction {index}: running balance disagrees")
        if kind == "qnb":
            debits = sum((r["amount"] for r in rows if r["direction"] == "Debit"), Decimal(0))
            credits = sum((r["amount"] for r in rows if r["direction"] == "Credit"), Decimal(0))
            if (debits, credits, running) != (total_debit, total_credit, closing):
                raise StatementError("QNB totals or closing balance disagree with all extracted rows")
        else:
            total_debit = sum((r["amount"] for r in rows if r["direction"] == "Debit"), Decimal(0))
            total_credit = sum((r["amount"] for r in rows if r["direction"] == "Credit"), Decimal(0))
        result = {"bank": kind, "pages": len(pdf), "rows": [
            {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            for row in rows], "opening": str(opening), "closing": str(closing),
            "total_debit": str(total_debit), "total_credit": str(total_credit),
            "account_number": _account_number(first, kind), "ocr_pages": ocr_pages}
        return result
    finally:
        pdf.close()


def _account_number(first, kind):
    if kind == "qnb":
        matches = re.findall(r"\b\d{4}-\d{6}-\d{3}\b", first)
    else:
        matches = re.findall(r"\b\d{4}-\d{7}-\d{3}-\d{4}-\d{3}\b", first)
    if not matches:
        raise StatementError("Bank account number is unreadable")
    return matches[0]
