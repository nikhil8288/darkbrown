"""Portfolio writes.

Building onboarding is one wizard that creates the building, the landlord and
every unit in one pass, or creates nothing at all. Partial portfolios are worse
than none: a building with half its units looks complete on every screen that
counts them.
"""

import frappe
from frappe import _
from frappe.utils import flt, cint

K = 1000.0


@frappe.whitelist()
def onboard_building(payload):
    """One atomic pass. Raises before anything commits if any part fails."""
    data = frappe.parse_json(payload)

    name = (data.get("building_name") or "").strip()
    if not name:
        frappe.throw(_("The building needs a name."))
    if frappe.db.exists("Building", name):
        frappe.throw(_("A building called {0} already exists.").format(name))

    units = data.get("units") or []
    if not units:
        frappe.throw(_("A building is onboarded with its units, not without "
                       "them."))
    numbers = [str(u.get("unit_no") or "").strip() for u in units]
    if not all(numbers):
        frappe.throw(_("Every unit needs a number matching its door."))
    if len(set(numbers)) != len(numbers):
        dupes = {n for n in numbers if numbers.count(n) > 1}
        frappe.throw(_("Duplicate unit numbers: {0}").format(
            ", ".join(sorted(dupes))))

    company = (data.get("company")
               or frappe.db.get_single_value("DBR Settings", "default_company")
               or frappe.defaults.get_user_default("Company"))
    if not company:
        frappe.throw(_("No company is set. Set one in DBR Settings first."))

    landlord = _landlord(data.get("landlord") or {})

    building = frappe.get_doc({
        "doctype": "Building",
        "building_name": name,
        "status": data.get("status") or "Onboarding",
        "landlord": landlord,
        "company": company,
        "area_name": data.get("area_name"),
        "municipality": data.get("municipality"),
        "zone_no": data.get("zone_no"),
        "street_no": data.get("street_no"),
        "building_no": data.get("building_no"),
        "floors": cint(data.get("floors")),
        "total_units": len(units),
        "parking_spaces": cint(data.get("parking_spaces")),
        "has_lift": cint(data.get("has_lift")),
        "kahramaa_account_no": data.get("kahramaa_account_no"),
        "handover_date": data.get("handover_date"),
    }).insert()

    for u in units:
        frappe.get_doc({
            "doctype": "Unit",
            "building": building.name,
            "unit_no": str(u.get("unit_no")).strip(),
            "floor": u.get("floor"),
            "unit_type": u.get("unit_type"),
            "status": u.get("status") or "Not Ready",
            "bedrooms": cint(u.get("bedrooms")),
            "bathrooms": cint(u.get("bathrooms")),
            "area_sqm": flt(u.get("area_sqm")),
            "asking_rent": flt(u.get("asking_rent")) * K,
            "furnishing": u.get("furnishing") or "Unfurnished",
            "landlord": landlord,
            "kahramaa_meter_no": u.get("kahramaa_meter_no"),
        }).insert()

    head_lease = None
    hl = data.get("head_lease") or {}
    if hl.get("annual_rent") and hl.get("start_date"):
        head_lease = frappe.get_doc({
            "doctype": "Head Lease",
            "building": building.name,
            "landlord": landlord,
            "company": company,
            "status": "Active",
            "start_date": hl.get("start_date"),
            "end_date": hl.get("end_date"),
            "annual_rent": flt(hl.get("annual_rent")) * K,
            "payment_frequency": hl.get("payment_frequency") or "Quarterly",
            "security_deposit": flt(hl.get("security_deposit")) * K,
            "units_covered": len(units),
            "signed_document": hl.get("signed_document"),
        }).insert().name

    return {"building": building.name, "units": len(units),
            "landlord": landlord, "head_lease": head_lease}


def _landlord(data):
    """The landlord is a party in its own right, not a text field on the
    building. Landlord documents file against the landlord."""
    name = (data.get("name") or "").strip()
    if not name:
        frappe.throw(_("The building needs a landlord."))
    if frappe.db.exists("Supplier", name):
        frappe.db.set_value("Supplier", name, "db_is_landlord", 1)
        return name
    group = (frappe.db.get_value("Supplier Group", {"supplier_group_name": "Services"}, "name")
             or frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"))
    # Nationality is a Link to Country. The wizard collects free text, so it is
    # only set when it resolves to a real Country; an unrecognised value is
    # dropped rather than failing the whole onboarding pass.
    nationality = (data.get("nationality") or "").strip()
    if nationality and not frappe.db.exists("Country", nationality):
        nationality = None

    doc = frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": name,
        "supplier_group": group,
        "db_is_landlord": 1,
        "db_landlord_qid": data.get("qid"),
        "db_nationality": nationality,
        "db_iban": data.get("iban"),
        "db_bank_name": data.get("bank"),
    })
    doc.flags.ignore_mandatory = True
    return doc.insert().name


@frappe.whitelist()
def set_unit_status(unit, status):
    allowed = frappe.get_meta("Unit").get_field("status").options.split("\n")
    if status not in allowed:
        frappe.throw(_("{0} is not a unit status.").format(status))
    if frappe.db.get_value("Unit", unit, "status") == "Occupied" \
            and status in ("Vacant", "Not Ready"):
        if frappe.db.exists("Tenancy Agreement",
                            {"unit": unit, "status": "Active"}):
            frappe.throw(_("That unit still has a live tenancy. Close it "
                           "through a move-out."))
    frappe.db.set_value("Unit", unit, "status", status)
    return {"unit": unit, "status": status}
