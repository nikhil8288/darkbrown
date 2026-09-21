"""Keep an Invoice Run usable when one of its invoices is cancelled."""

import frappe


def on_sales_invoice_cancel(doc, method=None):
    """Return affected issued runs to GM review for a replacement invoice.

    The cancelled Sales Invoice remains the accounting audit trail.  Clearing
    only the run-line pointer lets ``issue_invoice_run`` create a replacement
    while its persisted agreement/period duplicate key still protects every
    non-cancelled invoice.
    """
    lines = frappe.get_all(
        "Invoice Run Line",
        filters={"sales_invoice": doc.name, "parenttype": "Invoice Run"},
        fields=["name", "parent"],
    )
    parents = set()
    for line in lines:
        frappe.db.set_value(
            "Invoice Run Line", line.name, "sales_invoice", None,
            update_modified=False,
        )
        if line.parent:
            parents.add(line.parent)

    for run in parents:
        if frappe.db.get_value("Invoice Run", run, "status") == "Issued":
            frappe.db.set_value("Invoice Run", run, {
                "status": "Pending GM",
                "approved_by": None,
                "issued_on": None,
            })

