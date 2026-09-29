"""Administrator-only, bench-side, read-only site inventory. Not whitelisted.

No voucher/configuration writes, scheduler changes, cancellation or deletion.
Private output includes identifiers; never add it to Git or a deployment ZIP.
"""
import hashlib
import json
from pathlib import Path

from darkbrown.migration.evidence import digest, outside_repo

# All other doctypes are inventoried conservatively as preserved/unreviewed.
PROTECTED = {"Company", "Account", "Cost Center", "User", "Role", "Has Role",
             "User Permission", "DocType", "DocField", "Custom Field",
             "Property Setter", "Module Def", "DBR Settings", "Document Requirement",
             "Bank", "Bank Account", "Mode of Payment", "Mode of Payment Account",
             "Fiscal Year", "Fiscal Year Company", "Item", "Item Group", "UOM",
             "Customer Group", "Supplier Group", "Territory", "Currency"}
BUSINESS = {"Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry",
            "GL Entry", "Payment Ledger Entry", "Bank Transaction", "Bank Statement Import",
            "Payment Reconciliation", "Payment Request", "Payment Order", "Dunning",
            "Customer", "Supplier", "Employee", "Salary Slip", "Payroll Entry",
            "Expense Claim", "Asset", "Asset Movement", "Asset Repair", "Stock Entry",
            "File", "Communication", "ToDo", "Comment", "Version"}
FACTS = {"company", "building", "unit", "tenant", "landlord", "customer", "supplier",
         "posting_date", "transaction_date", "status", "disabled", "is_group",
         "parent_account", "account_type", "root_type", "account_currency",
         "default_currency", "default_receivable_account", "default_payable_account",
         "cost_center", "year_start_date", "year_end_date", "account",
         "is_company_account", "start_date", "end_date", "payment_frequency",
         "annual_rent", "monthly_rent", "due_date", "debit", "credit",
         "grand_total", "outstanding_amount", "paid_amount", "received_amount",
         "voucher_type", "voucher_no", "against_voucher_type", "against_voucher_no",
         "is_cancelled", "delinked", "reference_doctype", "reference_name",
         "attached_to_doctype", "attached_to_name", "is_private", "bank_account_no", "iban",
         "enabled", "stopped", "frequency", "method", "channel", "event",
         "rate", "qty", "amount", "base_amount", "account_head", "tax_amount"}


SECRET_NAMES = ("password", "secret", "token", "api_key", "private_key",
                "encryption_key", "credential", "authorization", "access_key", "passphrase",
                "signing_key", "auth_key" )
# Free-form Data/Text/Code/HTML settings can contain untyped secrets or URLs
# embedding credentials. Include Data only via FACTS or a relationship's type
# discriminator above; do not export arbitrary singleton strings.
SAFE_SETTING_TYPES = {"Select", "Check", "Int", "Float", "Currency", "Percent",
                      "Date", "Datetime", "Time", "Duration", "Link", "Dynamic Link"}


def safe_field(name, meta):
    field = meta.get_field(name)
    return not any(part in name.lower() for part in SECRET_NAMES) and not (
        field and field.fieldtype == "Password")


def record_inventory(frappe, dt, meta, links):
    """Read DB primitives only: never instantiate singleton controllers/onload."""
    selected = {"name", "modified", "docstatus"}
    selected |= {f.fieldname for f in links if f.fieldtype in ("Link", "Dynamic Link")}
    selected |= {f.options for f in links if f.fieldtype == "Dynamic Link" and meta.has_field(f.options)}
    selected |= {f for f in FACTS if meta.has_field(f)}
    if dt.istable:
        selected |= {"parent", "parenttype", "parentfield"}
    if dt.issingle:
        selected |= {f.fieldname for f in meta.fields if f.fieldtype in SAFE_SETTING_TYPES}
    selected = {f for f in selected if safe_field(f, meta)}
    if dt.issingle:
        # Include the singleton as a retained record so normal link analysis
        # sees its references. Read only approved fields, not get_doc/get_password.
        stored = [{"name": dt.name, **{f: frappe.db.get_single_value(dt.name, f)
                   for f in sorted(selected - {"name", "modified", "docstatus"})}}]
    else:
        stored = frappe.get_all(dt.name, fields=sorted(selected), order_by="name", limit_page_length=0)
    rows = [{**dict(row), "content_checksum": digest(dict(row))} for row in stored]
    disposition = ("preserve_setup" if dt.issingle or dt.name in PROTECTED else
                   "review_business" if dt.name in BUSINESS or dt.module == "Darkbrown" else "preserve_unreviewed")
    return {"module": dt.module, "istable": dt.istable, "issingle": dt.issingle,
            "disposition": disposition, "count": len(rows), "rows": rows}


def snapshot_checksum(snapshot):
    return digest({k: v for k, v in snapshot.items() if k not in {"captured_at", "snapshot_checksum"}})


def _admin(frappe):
    if frappe.session.user != "Administrator":
        raise frappe.PermissionError("Migration inventory requires the Administrator account")


def capture(company=None, expected_site=None):
    import frappe
    _admin(frappe)
    site = str(frappe.local.site)
    if not expected_site or site != expected_site:
        raise ValueError("Supply the exact bench site name as expected_site")
    companies = frappe.get_all("Company", fields=["name", "default_currency"], order_by="name")
    if company is not None and company not in {c.name for c in companies}:
        raise ValueError("Company must match an actual Company record")
    from frappe.utils import get_bench_path
    versions = {}
    for app in frappe.get_installed_apps():
        module = __import__(app)
        app_path = Path(get_bench_path()) / "apps" / app
        import subprocess
        ref = subprocess.run(["git", "-C", str(app_path), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False)
        versions[app] = {"version": getattr(module, "__version__", None),
                         "head": ref.stdout.strip() if ref.returncode == 0 else None}
    result = {"schema_version": 2, "site": site, "company": company,
              "companies": companies, "versions": versions,
              "captured_at": str(frappe.utils.now_datetime()),
              "records": {}, "relationships": [], "errors": [],
              "settings": {}, "cleanup_executable": False}
    # Enumerate every installed table's identifiers and relationship fields so
    # links from other apps cannot be silently ignored. Never export passwords,
    # tokens, identity documents, email bodies or file contents.
    for dt in frappe.get_all("DocType", fields=["name", "module", "istable", "issingle"], order_by="name"):
        try:
            meta = frappe.get_meta(dt.name)
            links = [f for f in meta.fields if f.fieldtype in ("Link", "Dynamic Link", "Table", "Table MultiSelect")]
            result["relationships"].extend({"doctype": dt.name, "field": f.fieldname,
                                             "type": f.fieldtype, "target": f.options} for f in links)
            if getattr(meta, "is_virtual", False):
                result["errors"].append({"doctype": dt.name, "error": "virtual doctype: manual review"})
                continue
            for f in links:
                if f.fieldtype in ("Link", "Dynamic Link") and (
                    not safe_field(f.fieldname, meta) or
                    (f.fieldtype == "Dynamic Link" and not safe_field(f.options, meta))):
                    result["errors"].append({"doctype": dt.name, "error": "secret relationship excluded; manual dependency review required"})
            result["records"][dt.name] = record_inventory(frappe, dt, meta, links)
        except Exception as exc:
            # Failure never becomes a fictitious zero count or a complete graph.
            result["errors"].append({"doctype": dt.name, "error": type(exc).__name__})
    for dt, fields in {
        "System Settings": ["time_zone", "enable_scheduler"],
        "Accounts Settings": ["acc_frozen_upto", "frozen_accounts_modifier", "backdated_transactions_authorized_role"],
        "DBR Settings": ["default_company", "invoice_generation_day", "grace_days"],
    }.items():
        meta = frappe.get_meta(dt)
        result["settings"][dt] = {f: frappe.db.get_single_value(dt, f) for f in fields if meta.has_field(f)}
    result["settings"]["site_switches"] = {k: frappe.conf.get(k) for k in
        ("pause_scheduler", "maintenance_mode", "mute_emails", "darkbrown_migration_in_progress")}
    result["snapshot_checksum"] = snapshot_checksum(result)
    return result


def export(expected_site=None, company=None, output_name="migration-inventory.json"):
    import frappe
    _admin(frappe)
    if Path(output_name).name != output_name or not output_name.endswith(".json"):
        raise ValueError("output_name must be a JSON basename")
    result = capture(company=company, expected_site=expected_site)
    directory = outside_repo(Path(frappe.get_site_path("private", "migration-review")))
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / output_name
    with destination.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, default=str)
    return {"private_path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "company_names": [c.name for c in result["companies"]],
            "doctypes": len(result["records"]), "unreadable_doctypes": len(result["errors"]),
            "production_writes": 0}
