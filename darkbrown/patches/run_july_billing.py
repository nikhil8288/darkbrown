"""DISABLED. This was a test-phase patch and it must not run against real data.

WHAT IT DID

It generated July 2026 invoices, SUBMITTED them, and opened Collection Cases -
automatically, during `bench migrate`. To do that it monkey-patched ERPNext's
`validate_due_date` to a no-op in two modules for the duration of the run,
because the invoice builder it called posted with today's date and a due date
inside the period, which core ERPNext refuses. Every failure was caught and
printed, so a bad run left no trace beyond a line in a migrate log.

WHY IT IS GONE RATHER THAN FIXED

The bug it worked around lived in `utils.rent_invoicing`, which was a dead
second copy of the invoice builder. That copy has been removed. The live engine
in `api.finance` posts at `run.period_start` and derives the due date forward
from there, so it never needed the workaround.

Suppressing a core accounting validation during an unattended deploy should not
be reachable at all on a site carrying a real ledger, so this file refuses
rather than merely being unregistered in patches.txt. Deleting it is better
still - an overlay cannot delete, so see DEPLOY.md:

    git rm darkbrown/patches/run_july_billing.py

HOW TO ACTUALLY BILL A MONTH

Per building, as a decision someone takes:

    api.finance.build_invoice_run(building, period_start)   -> drafts the run
    api.finance.submit_invoice_run(run)                     -> to the GM
    api.finance.issue_invoice_run(run)                      -> posts the invoices

`utils.rent_invoicing.monthly_reminder` runs on the configured day and tells
Accounts which buildings are still outstanding.
"""

import frappe

_REFUSAL = (
    "run_july_billing is disabled. It submitted invoices during migrate with "
    "ERPNext's due-date validation monkey-patched out. Use "
    "api.finance.build_invoice_run / submit_invoice_run / issue_invoice_run, "
    "which post at the period start and need no workaround. See the module "
    "docstring."
)


def execute():
    """Patch entrypoint. Refuses loudly instead of billing."""
    frappe.throw(_REFUSAL)


def run(*args, **kwargs):
    frappe.throw(_REFUSAL)
