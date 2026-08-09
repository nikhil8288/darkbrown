"""Portfolio writes.

Building onboarding is one wizard that creates the building, the landlord and
every unit in one pass, or creates nothing at all. Partial portfolios are worse
than none: a building with half its units looks complete on every screen that
counts them.
"""

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, today
from darkbrown.guards import guard, GM, MD, MNT

@frappe.whitelist()
def onboard_building(payload):
    """One atomic pass. Raises before anything commits if any part fails."""
    guard(MD, GM)
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
            "asking_rent": flt(u.get("asking_rent")),
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
            "annual_rent": flt(hl.get("annual_rent")),
            "payment_frequency": hl.get("payment_frequency") or "Quarterly",
            "security_deposit": flt(hl.get("security_deposit")),
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

    # The wizard asks for the landlord's type, mobile, email and
    # representative and they were all discarded here, so every landlord read
    # back with a dash against the very fields somebody had just typed. A
    # company is identified by its CR number, a person by their QID; the same
    # box on the form feeds whichever the type calls for.
    company = (data.get("type") or "").strip().lower() == "company"
    ident = (data.get("qid") or "").strip() or None

    doc = frappe.get_doc({
        "doctype": "Supplier",
        "supplier_name": name,
        "supplier_group": group,
        "supplier_type": "Company" if company else "Individual",
        "db_is_landlord": 1,
        "db_landlord_cr_no": ident if company else None,
        "db_landlord_qid": None if company else ident,
        "db_landlord_mobile": data.get("mobile"),
        "db_representative_name": data.get("representative"),
        "email_id": data.get("email"),
        "db_nationality": nationality,
        "db_iban": data.get("iban"),
        "db_bank_name": data.get("bank"),
    })
    doc.flags.ignore_mandatory = True
    return doc.insert().name


@frappe.whitelist()
def record_handover(building, handover_date=None, ready_units=1):
    """The landlord has handed the building over. It is now trading.

    Onboarding created the building in status Onboarding and the success
    message told you it would stay there "until handover is recorded" — and
    then nothing in the application could record one. A building therefore sat
    in Onboarding for its whole life, and `handover_date` was a field the
    wizard accepted and the screen never sent.

    Three things happen together because they are one event: the date is
    written, the building starts trading, and any unit still marked Not Ready
    becomes lettable. Units already Occupied, Reserved or Under Maintenance are
    left exactly as they are — handover is a fact about the building, and it
    must not overwrite what somebody has said about a particular door.
    """
    guard(MD, GM)
    if not frappe.db.exists("Building", building):
        frappe.throw(_("No building called {0}.").format(building))

    doc = frappe.get_doc("Building", building)
    if doc.status not in ("Onboarding", "Active"):
        frappe.throw(_("{0} is {1}. Handover is recorded on a building that "
                       "is still onboarding.").format(building, doc.status))

    on = getdate(handover_date or today())
    if doc.exit_date and getdate(doc.exit_date) < on:
        frappe.throw(_("Handover cannot fall after the exit date already "
                       "recorded on this building."))

    doc.handover_date = on
    doc.status = "Active"
    doc.save()

    readied = 0
    if cint(ready_units):
        not_ready = frappe.get_all("Unit",
                                   filters={"building": building,
                                            "status": "Not Ready"},
                                   pluck="name")
        for name in not_ready:
            frappe.db.set_value("Unit", name, "status", "Vacant")
        readied = len(not_ready)

    return {"building": building, "handover_date": str(on),
            "status": doc.status, "units_readied": readied}


@frappe.whitelist()
def set_unit_status(unit, status):
    """Readiness, set by hand.

    Occupancy is not settable here. A unit becomes Occupied when a tenancy is
    activated and stops being Occupied through a move-out; letting the two
    disagree is how a unit ends up let on one screen and empty on another.
    """
    guard(MD, GM, MNT)
    if not frappe.db.exists("Unit", unit):
        frappe.throw(_("No unit called {0}.").format(unit))
    allowed = frappe.get_meta("Unit").get_field("status").options.split("\n")
    if status not in allowed:
        frappe.throw(_("{0} is not a unit status.").format(status))
    if status == "Occupied":
        frappe.throw(_("A unit becomes occupied when its tenancy is "
                       "activated, not by hand."))
    if frappe.db.get_value("Unit", unit, "status") == "Occupied" \
            and status in ("Vacant", "Not Ready"):
        if frappe.db.exists("Tenancy Agreement",
                            {"unit": unit, "status": "Active"}):
            frappe.throw(_("That unit still has a live tenancy. Close it "
                           "through a move-out."))
    frappe.db.set_value("Unit", unit, "status", status)
    return {"unit": unit, "status": status}


@frappe.whitelist()
def add_unit(data):
    """Add one unit to a building that already exists.

    Onboarding was the only path that ever created a Unit, so a building that
    gained a floor after it was set up could not be corrected without going
    into the desk. The field list and the defaults are deliberately identical
    to the onboarding loop above, so a unit added here is indistinguishable
    from one created with its building.
    """
    guard(MD, GM)
    data = frappe.parse_json(data) or {}

    building = (data.get("building") or "").strip()
    if not building:
        frappe.throw(_("Which building is the unit in?"))
    if not frappe.db.exists("Building", building):
        frappe.throw(_("No building called {0}.").format(building))

    unit_no = str(data.get("unit_no") or "").strip()
    if not unit_no:
        frappe.throw(_("Every unit needs a number matching its door."))
    if frappe.db.exists("Unit", {"building": building, "unit_no": unit_no}):
        frappe.throw(_("{0} already has a unit {1}.").format(
            building, unit_no))

    doc = frappe.get_doc({
        "doctype": "Unit",
        "building": building,
        "unit_no": unit_no,
        "floor": data.get("floor"),
        "unit_type": data.get("unit_type"),
        "status": data.get("status") or "Not Ready",
        "bedrooms": cint(data.get("bedrooms")),
        "bathrooms": cint(data.get("bathrooms")),
        "area_sqm": flt(data.get("area_sqm")),
        "asking_rent": flt(data.get("asking_rent")),
        "furnishing": data.get("furnishing") or "Unfurnished",
        "landlord": frappe.db.get_value("Building", building, "landlord"),
        "kahramaa_meter_no": data.get("kahramaa_meter_no"),
    }).insert()

    # total_units is written by onboarding from the length of its list, so it
    # has to be kept true here rather than left at its founding value.
    frappe.db.set_value("Building", building, "total_units",
                        frappe.db.count("Unit", {"building": building}))

    return {"unit": doc.name, "unit_no": unit_no, "building": building}
