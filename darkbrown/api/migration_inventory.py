"""Read-only Administrator inventory downloads; no File or financial writes."""
import json

import frappe
from werkzeug.wrappers import Response

from darkbrown.migration.inventory import _admin, capture


def _response(payload, attachment=False):
    response = Response(json.dumps(payload, ensure_ascii=False, default=str),
                        content_type="application/json; charset=utf-8")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if attachment:
        response.headers["Content-Disposition"] = 'attachment; filename="darkbrown-migration-inventory.json"'
    return response


@frappe.whitelist(methods=["POST"])
def context():
    _admin(frappe)
    return _response({"message": {
        "site": str(frappe.local.site),
        "companies": frappe.get_all("Company", pluck="name", order_by="name"),
    }})


@frappe.whitelist(methods=["POST"])
def download(company=None, expected_site=None):
    _admin(frappe)
    if not isinstance(company, str) or not company.strip():
        raise ValueError("Select an actual Company before exporting")
    # capture validates exact site and company, excludes secret fields, retains
    # explicit errors and produces the same v2 checksum as the bench exporter.
    result = capture(company=company, expected_site=expected_site)
    return _response(result, attachment=True)
