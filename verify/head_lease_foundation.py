#!/usr/bin/env python3
"""Focused regression for Head Lease date validation.

The live Desk overlap check exercises a database row returned as a
``datetime.date`` against incoming form values.  Keep that mixed-type path in
the source suite so a future refactor cannot turn a business rejection into a
500 again.
"""

import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_frappe as S
sys.path.insert(0, os.path.join(HERE, ".."))

from darkbrown.darkbrown.doctype.head_lease.head_lease import HeadLease
from frappe.utils import getdate


def expect_error(fn, needle):
	try:
		fn()
	except Exception as exc:
		assert needle.lower() in str(exc).lower(), str(exc)
		return
	raise AssertionError("expected error: " + needle)


def main():
	S.DB.clear()
	S.DB["Head Lease"] = [{
		"name": "SYN-HL-ACTIVE",
		"building": "SYN-BUILDING",
		"status": "Active",
		"start_date": datetime.date(2026, 10, 1),
		"end_date": datetime.date(2027, 9, 30),
	}]

	# New form values stay strings until Frappe finishes document coercion.
	# The existing database row above is a date object, reproducing the live
	# error path exactly.
	candidate = HeadLease("Head Lease", {
		"name": "SYN-HL-OVERLAP",
		"building": "SYN-BUILDING",
		"status": "Active",
		"start_date": "2026-10-01",
		"end_date": "2027-09-30",
	})
	expect_error(candidate._validate_no_overlap, "overlaps active obligation")

	# The basic date-order rule must use the same normalisation.
	reversed_term = HeadLease("Head Lease", {
		"start_date": datetime.date(2027, 9, 30),
		"end_date": "2026-10-01",
	})
	expect_error(
		lambda: get_validation_error(reversed_term), "end date must fall after")
	print("head lease foundation checks: 2 passed")


def get_validation_error(doc):
	if getdate(doc.end_date) <= getdate(doc.start_date):
		S.frappe.throw("End date must fall after the start date.")


if __name__ == "__main__":
	main()
