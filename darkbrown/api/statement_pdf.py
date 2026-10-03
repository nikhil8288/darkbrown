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


def _row(words, kind, page):
    start = words[0]
    if kind == "qnb":
        debit = _money(words, 290, 375, "debit")
        credit = _money(words, 375, 470, "credit")
        balance = _money(words, 470, 590, "balance")
        date = _date(start[4], "%d/%m/%Y")
        narrative = " ".join(w[4] for w in words if 90 <= w[0] < 290)
        ref = next((w[4] for w in words if 90 <= w[0] < 290
                    and re.search(r"\d{5,}", w[4])), "")
        value_date = None
    else:
        debit = _money(words, 670, 715, "debit")
        credit = _money(words, 715, 759, "credit")
        balance = _money(words, 759, 841, "balance")
        date = _date(start[4], "%d-%m-%Y")
        refs = [w[4] for w in words if 115 <= w[0] < 180 and abs(w[1] - start[1]) < 4]
        ref = refs[0] if refs else ""
        narrative = " ".join(w[4] for w in words if 180 <= w[0] < 620)
        dates = [w[4] for w in words if 620 <= w[0] < 670 and DATE_DOHA.fullmatch(w[4])]
        value_date = _date(dates[0], "%d-%m-%Y") if dates else None
    if (debit is None) == (credit is None) or balance is None:
        raise StatementError(f"Page {page}: transaction needs exactly one debit or credit and a balance")
    if (credit is not None and credit <= 0) or (debit is not None and debit == 0):
        raise StatementError(f"Page {page}: invalid signed amount")
    signed = credit if credit is not None else -abs(debit)
    if signed == 0:
        raise StatementError(f"Page {page}: zero transaction amount")
    return {"date": date, "value_date": value_date, "ref": ref,
            "narrative": narrative.strip(), "amount": abs(signed),
            "direction": "Credit" if signed > 0 else "Debit",
            "balance": balance, "page": page}


def parse_statement(data):
    """Return validated rows and provenance for a QNB or Doha Bank digital PDF.

    No image OCR is attempted here. Scanned files fail with an actionable error.
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
        first = pdf[0].get_text()
        kind = ("qnb" if "Qatar National Bank" in first and "ACCOUNT SUMMARY" in first
                else "doha" if "Doha Bank" in first and "Datewise Account Transactions" in first
                else None)
        if not kind:
            raise StatementError("Unknown bank statement layout or scanned PDF; review required")
        rows, current, headings = [], [], []
        for page_index, page in enumerate(pdf):
            page_no = page_index + 1
            text = page.get_text()
            if len(text.strip()) < 100:
                raise StatementError(f"Page {page_no} has no readable text; OCR review required")
            if kind == "qnb" and "Bank Statement" not in text:
                raise StatementError(f"Page {page_no} is not a QNB statement page")
            if kind == "doha" and not re.search(r"Copyright\s+\d{4}.*Doha Bank", text):
                raise StatementError(f"Page {page_no} is not a Doha statement page")
            page_marker = (re.search(r"Page\s+(\d+)\s+of\s+(\d+)", text)
                           if kind == "qnb" else
                           re.search(r"(\d+)\s+of\s+(\d+)\s*\Z", text.strip()))
            if not page_marker or (int(page_marker[1]), int(page_marker[2])) != (page_no, len(pdf)):
                raise StatementError(f"Page {page_no}: page numbering or total pages disagree")
            words = page.get_text("words", sort=True)
            date_pattern = DATE_QNB if kind == "qnb" else DATE_DOHA
            left = 37 if kind == "qnb" else 44
            for word in words:
                x, y, _, _, value, *_ = word
                if abs(x - left) < 3 and date_pattern.fullmatch(value):
                    if current:
                        rows.append(_row(current, kind, headings[-1]))
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
                rows.append(_row(current, kind, headings[-1]))
                current = []
        if current:
            rows.append(_row(current, kind, headings[-1]))
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
            total_debit = sum((r["amount"] for r in rows if r["direction"] == "Debit"), Decimal(0))
            total_credit = sum((r["amount"] for r in rows if r["direction"] == "Credit"), Decimal(0))
            opening = rows[0]["balance"] - (rows[0]["amount"] if rows[0]["direction"] == "Credit" else -rows[0]["amount"])
            closing = rows[-1]["balance"]
        running = opening
        for index, row in enumerate(rows, 1):
            running += row["amount"] if row["direction"] == "Credit" else -row["amount"]
            if running != row["balance"]:
                raise StatementError(f"Page {row['page']}, transaction {index}: running balance disagrees")
        if kind == "qnb":
            debits = sum((r["amount"] for r in rows if r["direction"] == "Debit"), Decimal(0))
            credits = sum((r["amount"] for r in rows if r["direction"] == "Credit"), Decimal(0))
            if (debits, credits, running) != (total_debit, total_credit, closing):
                raise StatementError("QNB totals or closing balance disagree with all extracted rows")
        result = {"bank": kind, "pages": len(pdf), "rows": [
            {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            for row in rows], "opening": str(opening), "closing": str(closing),
            "total_debit": str(total_debit), "total_credit": str(total_credit),
            "account_number": _account_number(first, kind)}
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
