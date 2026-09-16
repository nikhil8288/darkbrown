#!/usr/bin/env python3
"""Focused source/stub regression for Step 2 tenancy/accounting invariants."""

import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_frappe as S
sys.path.insert(0, os.path.join(HERE, ".."))

from darkbrown.api import agreements


def reset():
    S.CALLS[:] = []
    S.THROWN[:] = []
    S.DB.clear()
    S.SESSION["user"] = "md@example.invalid"
    S.SESSION["roles"] = ["Managing Director"]
    S.frappe.session.user = S.SESSION["user"]
    S.SCHEMA.update({
        "Customer": {"db_is_tenant": ("Check", None)},
        "Supplier": {"db_is_landlord": ("Check", None)},
        "Tenancy Agreement": {
            "tenant": ("Link", "Customer"), "unit": ("Link", "Unit"),
            "building": ("Link", "Building"), "company": ("Link", "Company"),
            "status": ("Select", "Draft\nPending Approval\nActive\nExpiring\nExpired\nTerminated", "Draft"),
            "start_date": ("Date", None), "end_date": ("Date", None),
            "monthly_rent": ("Currency", "QAR"), "security_deposit": ("Currency", "QAR"),
            "notice_days": ("Int", None), "payment_mode": ("Select", "Cheque\nCash\nTransfer"),
            "payment_frequency": ("Select", "Monthly\nQuarterly\nHalf Yearly\nAnnual"),
            "cheques_held": ("Int", None), "qid_number": ("Data", None),
            "signed_pack": ("Attach", None), "activation_route": ("Data", None),
            "missing_items": ("Small Text", None), "approved_by": ("Link", "User"),
            "approved_on": ("Datetime", None), "notes": ("Text", None),
            "renewal_of": ("Link", "Tenancy Agreement"), "auto_renew": ("Check", None),
            "charges": ("Table", "Tenancy Charge"), "passport_no": ("Data", None),
            "mobile_no": ("Data", None), "qid_expiry": ("Date", None),
        },
        "Unit": {"building": ("Link", "Building"), "status": ("Select", "Not Ready\nVacant\nReserved\nOccupied\nUnder Maintenance")},
    })
    S.DB.update({
        "DBR Settings": [{"name": "DBR Settings", "default_company": "SYN-QAR", "default_tenancy_notice_days": 60}],
        "Company": [{"name": "SYN-QAR", "default_currency": "QAR"}],
        "Building": [{"name": "SYN-A", "company": "SYN-QAR"}, {"name": "SYN-B", "company": "SYN-QAR"}],
        "Unit": [{"name": "SYN-A-A01", "building": "SYN-A", "status": "Vacant"},
                 {"name": "SYN-B-B01", "building": "SYN-B", "status": "Vacant"}],
        "Customer": [{"name": "SYN-TENANT-A", "db_is_tenant": 1}],
    })


def payload(**overrides):
    data = {"unit": "SYN-A-A01", "tenant": "SYN-TENANT-A",
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "rent": 1500, "deposit": 1500, "payment_mode": "Cash",
            "payment_frequency": "Monthly", "qid": "SYN-ID",
            "signed_pack": "/private/files/SYN-SIGNED.pdf"}
    data.update(overrides)
    return json.dumps(data)


def expect_error(fn, needle):
    try:
        fn()
    except Exception as exc:
        assert needle.lower() in str(exc).lower(), str(exc)
        return
    raise AssertionError("expected error: " + needle)


def main():
    reset()
    made = agreements.create_agreement(payload())
    assert made["status"] == "Pending Approval"
    assert not S.DB.get("GL Entry") and not S.DB.get("Security Deposit")
    name = made["agreement"]
    activated = agreements.activate(name, "synthetic approval")
    assert activated["status"] == "Active"
    assert S.frappe.db.get_value("Unit", "SYN-A-A01", "status") == "Occupied"
    assert not S.DB.get("GL Entry") and not S.DB.get("Security Deposit")

    expect_error(lambda: agreements.create_agreement(payload(
        start_date="2026-06-01", end_date="2027-05-31")), "overlapping")
    expect_error(lambda: agreements.create_agreement(payload(rent=-1)), "negative")

    # Building is derived from Unit; no client value can move an agreement to B.
    draft = S.frappe.get_doc("Tenancy Agreement", name)
    draft["building"] = "SYN-B"
    expect_error(lambda: draft.save(ignore_permissions=True), "must match")

    old_status = S.frappe.db.get_value("Tenancy Agreement", name, "status")
    renewed = agreements.renew(name, payload(
        start_date="2027-01-01", end_date="2027-12-31", save_as_draft=True))
    assert renewed["status"] == "Draft"
    assert S.frappe.db.get_value("Tenancy Agreement", name, "status") == old_status

    source = Path("darkbrown/api/agreements.py").read_text()
    assert "Security Deposit" not in source
    assert "Self Approved" not in source
    print("tenancy/accounting foundation checks: 8 passed")


if __name__ == "__main__":
    main()
