"""The dummy portfolio.

A miniature of the real business: three buildings, twenty-four units, twenty
tenancies, two banks, one shop. Small enough to read end to end on a screen,
large enough that every branch in the application has something to land on —
a void, a bounce, an arrears case, an over-ceiling job, a move-out, an
amendment waiting on the MD.

Nothing here is real. Names, QIDs, IBANs and cheque numbers are invented.
Amounts are in QAR and are written in full, not in thousands; the API layer
multiplies by a thousand where the wizard collects thousands, and seed.py
divides before calling it. Keeping this file in full riyals means it can be
read against a bank statement without arithmetic.

Dates are anchored to the month the seeder runs in, so the demo is always
current no matter when it is rebuilt.
"""

from frappe.utils import add_months, get_first_day, get_last_day, add_days, today


# --------------------------------------------------------------- date anchors

def anchors():
    """Every date in the dataset hangs off these."""
    m0 = get_first_day(today())          # first day of the current month
    return {
        "m0": m0,
        "m1": get_first_day(add_months(m0, -1)),
        "m2": get_first_day(add_months(m0, -2)),
        "m3": get_first_day(add_months(m0, -3)),
        "m0_end": get_last_day(m0),
        "today": today(),
    }


def _rel(months, day=1):
    """A date `months` away from the first of the current month."""
    base = get_first_day(add_months(get_first_day(today()), months))
    return add_days(base, day - 1)


# ----------------------------------------------------------------- landlords

LANDLORDS = {
    "mannai": {
        "name": "Abdulla Nasser Al-Mannai",
        "qid": "28563401299",
        "nationality": "Qatar",
        "iban": "QA58QNBA000000000000012345678",
        "bank": "Qatar National Bank",
    },
    "rayyan": {
        "name": "Al Rayyan Properties W.L.L.",
        "qid": "CR-78412",
        "nationality": "Qatar",
        "iban": "QA31DOHB000000000000098765432",
        "bank": "Doha Bank",
    },
    "kuwari": {
        "name": "Hamad Jassim Al-Kuwari",
        "qid": "27741900855",
        "nationality": "Qatar",
        "iban": "QA77CBQA000000000000045612378",
        "bank": "Commercial Bank of Qatar",
    },
}


# ----------------------------------------------------------------- buildings
#
# annual_rent and security_deposit are in full QAR. head-lease months are
# offsets from the first of the current month, so every lease is live and one
# of them is inside its notice window.

BUILDINGS = [
    {
        "key": "najma",
        "building_name": "Najma Tower",
        "landlord": "mannai",
        "area_name": "Najma",
        "municipality": "Ad Dawhah",
        "zone_no": "27",
        "street_no": "850",
        "building_no": "14",
        "floors": 8,
        "parking_spaces": 10,
        "has_lift": 1,
        "kahramaa_account_no": "KM-27-0850-014",
        "handover_months": -11,
        "head_lease": {
            "annual_rent": 780000,
            "security_deposit": 65000,
            "payment_frequency": "Quarterly",
            "start_months": -10,
            "months": 12,
        },
        "units": [
            {"unit_no": "101", "floor": "1", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-101-27"},
            {"unit_no": "102", "floor": "1", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 94, "furnishing": "Semi Furnished", "meter": "K-102-27"},
            {"unit_no": "201", "floor": "2", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 68, "furnishing": "Fully Furnished", "meter": "K-201-27"},
            {"unit_no": "202", "floor": "2", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-202-27"},
            {"unit_no": "301", "floor": "3", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-301-27"},
            {"unit_no": "302", "floor": "3", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 66, "furnishing": "Unfurnished", "meter": "K-302-27"},
            {"unit_no": "401", "floor": "4", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 98, "furnishing": "Fully Furnished", "meter": "K-401-27"},
            {"unit_no": "402", "floor": "4", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-402-27"},
            {"unit_no": "501", "floor": "5", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-501-27"},
            {"unit_no": "502", "floor": "5", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 68, "furnishing": "Unfurnished", "meter": "K-502-27"},
            {"unit_no": "601", "floor": "6", "unit_type": "3BR", "bedrooms": 3, "bathrooms": 3, "area_sqm": 142, "furnishing": "Fully Furnished", "meter": "K-601-27"},
            {"unit_no": "602", "floor": "6", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 96, "furnishing": "Semi Furnished", "meter": "K-602-27"},
        ],
    },
    {
        "key": "binmahmoud",
        "building_name": "Bin Mahmoud Residency",
        "landlord": "rayyan",
        "area_name": "Fereej Bin Mahmoud",
        "municipality": "Ad Dawhah",
        "zone_no": "23",
        "street_no": "230",
        "building_no": "62",
        "floors": 5,
        "parking_spaces": 6,
        "has_lift": 0,
        "kahramaa_account_no": "KM-23-0230-062",
        "handover_months": -9,
        "head_lease": {
            "annual_rent": 456000,
            "security_deposit": 38000,
            "payment_frequency": "Quarterly",
            "start_months": -8,
            "months": 12,
        },
        "units": [
            {"unit_no": "G1", "floor": "G", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 62, "furnishing": "Unfurnished", "meter": "K-G1-23"},
            {"unit_no": "G2", "floor": "G", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 60, "furnishing": "Unfurnished", "meter": "K-G2-23"},
            {"unit_no": "1A", "floor": "1", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 88, "furnishing": "Semi Furnished", "meter": "K-1A-23"},
            {"unit_no": "1B", "floor": "1", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 88, "furnishing": "Semi Furnished", "meter": "K-1B-23"},
            {"unit_no": "2A", "floor": "2", "unit_type": "Studio", "bedrooms": 0, "bathrooms": 1, "area_sqm": 42, "furnishing": "Fully Furnished", "meter": "K-2A-23"},
            {"unit_no": "2B", "floor": "2", "unit_type": "2BR", "bedrooms": 2, "bathrooms": 2, "area_sqm": 86, "furnishing": "Unfurnished", "meter": "K-2B-23"},
            {"unit_no": "3A", "floor": "3", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 64, "furnishing": "Semi Furnished", "meter": "K-3A-23"},
            {"unit_no": "3B", "floor": "3", "unit_type": "1BR", "bedrooms": 1, "bathrooms": 1, "area_sqm": 64, "furnishing": "Semi Furnished", "meter": "K-3B-23"},
        ],
    },
    {
        "key": "alsadd",
        "building_name": "Al Sadd Court",
        "landlord": "kuwari",
        "area_name": "Al Sadd",
        "municipality": "Ad Dawhah",
        "zone_no": "38",
        "street_no": "810",
        "building_no": "7",
        "floors": 4,
        "parking_spaces": 4,
        "has_lift": 0,
        "kahramaa_account_no": "KM-38-0810-007",
        "handover_months": -6,
        "head_lease": {
            "annual_rent": 240000,
            "security_deposit": 20000,
            "payment_frequency": "Quarterly",
            "start_months": -5,
            "months": 12,
        },
        "units": [
            {"unit_no": "S1", "floor": "G", "unit_type": "Shop", "bedrooms": 0, "bathrooms": 1, "area_sqm": 74, "furnishing": "Unfurnished", "meter": "K-S1-38"},
            {"unit_no": "1", "floor": "1", "unit_type": "3BR", "bedrooms": 3, "bathrooms": 3, "area_sqm": 138, "furnishing": "Semi Furnished", "meter": "K-1-38"},
            {"unit_no": "2", "floor": "2", "unit_type": "3BR", "bedrooms": 3, "bathrooms": 3, "area_sqm": 138, "furnishing": "Semi Furnished", "meter": "K-2-38"},
            {"unit_no": "3", "floor": "3", "unit_type": "3BR", "bedrooms": 3, "bathrooms": 3, "area_sqm": 138, "furnishing": "Unfurnished", "meter": "K-3-38"},
        ],
    },
]


# ----------------------------------------------------------------- tenancies
#
# `route` decides how the agreement lands:
#   "self"    — complete paperwork, self-approves to Active
#   "override" — QID missing, routes for approval, then activated on override
#   "pending" — signed pack missing, left sitting in the approvals queue
#
# rent and deposit are full QAR. `cheques` is how many PDCs were handed over.

TENANCIES = [
    # -- Najma Tower ------------------------------------------------------
    {"building": "najma", "unit": "101", "tenant": "Rajesh Kumar Nair", "qid": "28912400177", "mobile": "+974 3312 4477", "rent": 8500, "deposit": 8500, "mode": "Cheque", "cheques": 12, "start_months": -9, "route": "self", "bank": "Qatar National Bank", "first_cheque": "410221"},
    {"building": "najma", "unit": "102", "tenant": "Mohammed Farooq Ali", "qid": "27804500391", "mobile": "+974 5566 1209", "rent": 8200, "deposit": 8200, "mode": "Cheque", "cheques": 12, "start_months": -9, "route": "self", "bank": "Doha Bank", "first_cheque": "778301"},
    {"building": "najma", "unit": "201", "tenant": "Sunita Menon", "qid": "29011700823", "mobile": "+974 3390 8812", "rent": 6500, "deposit": 6500, "mode": "Cheque", "cheques": 12, "start_months": -8, "route": "self", "bank": "Qatar National Bank", "first_cheque": "410455"},
    {"building": "najma", "unit": "202", "tenant": "Ahmed Salem Al-Hajri", "qid": "28650200144", "mobile": "+974 5511 3376", "rent": 8800, "deposit": 8800, "mode": "Cheque", "cheques": 12, "start_months": -8, "route": "self", "bank": "Commercial Bank of Qatar", "first_cheque": "902114"},
    {"building": "najma", "unit": "301", "tenant": "Priya Ramachandran", "qid": "29103300668", "mobile": "+974 7788 4423", "rent": 8500, "deposit": 8500, "mode": "Cheque", "cheques": 12, "start_months": -7, "route": "self", "bank": "Qatar National Bank", "first_cheque": "410730"},
    {"building": "najma", "unit": "302", "tenant": "Ibrahim Konate", "qid": "28522900412", "mobile": "+974 3345 9901", "rent": 6300, "deposit": 6300, "mode": "Cash", "cheques": 0, "start_months": -6, "route": "self"},
    {"building": "najma", "unit": "401", "tenant": "Elena Petrova", "qid": "29208800257", "mobile": "+974 5599 2038", "rent": 9000, "deposit": 9000, "mode": "Cheque", "cheques": 12, "start_months": -6, "route": "self", "bank": "Doha Bank", "first_cheque": "778955"},
    {"building": "najma", "unit": "501", "tenant": "Anil Joseph Thomas", "qid": "28733600509", "mobile": "+974 3367 7714", "rent": 8600, "deposit": 8600, "mode": "Cheque", "cheques": 12, "start_months": -10, "route": "self", "bank": "Qatar National Bank", "first_cheque": "411002"},
    {"building": "najma", "unit": "502", "tenant": "Fatima Zahra Bennani", "qid": None, "mobile": "+974 7712 5560", "rent": 6400, "deposit": 6400, "mode": "Cheque", "cheques": 12, "start_months": -3, "route": "override", "bank": "Doha Bank", "first_cheque": "779240"},
    {"building": "najma", "unit": "601", "tenant": "Gulf Horizon Trading W.L.L.", "corporate": True, "cr_no": "CR-91277", "qid": "CR-91277", "mobile": "+974 4455 8800", "rent": 11500, "deposit": 23000, "mode": "Cheque", "cheques": 12, "start_months": -11, "route": "self", "bank": "Commercial Bank of Qatar", "first_cheque": "902880"},

    # -- Bin Mahmoud Residency -------------------------------------------
    {"building": "binmahmoud", "unit": "G1", "tenant": "Samuel Okonkwo", "qid": "29055100734", "mobile": "+974 3321 6690", "rent": 5800, "deposit": 5800, "mode": "Cash", "cheques": 0, "start_months": -7, "route": "self"},
    {"building": "binmahmoud", "unit": "G2", "tenant": "Maria Dela Cruz", "qid": "28944700118", "mobile": "+974 5533 0074", "rent": 5600, "deposit": 5600, "mode": "Cash", "cheques": 0, "start_months": -7, "route": "self"},
    {"building": "binmahmoud", "unit": "1A", "tenant": "Kiran Prasad", "qid": "28811200962", "mobile": "+974 7745 3319", "rent": 7200, "deposit": 7200, "mode": "Cheque", "cheques": 12, "start_months": -6, "route": "self", "bank": "Qatar National Bank", "first_cheque": "411510"},
    {"building": "binmahmoud", "unit": "1B", "tenant": "Nasser Al-Dosari", "qid": "28477000283", "mobile": "+974 5502 7745", "rent": 7400, "deposit": 7400, "mode": "Cheque", "cheques": 12, "start_months": -6, "route": "self", "bank": "Doha Bank", "first_cheque": "780113"},
    {"building": "binmahmoud", "unit": "2A", "tenant": "Aisha Rahman", "qid": "29166400571", "mobile": "+974 3308 4426", "rent": 4200, "deposit": 4200, "mode": "Cash", "cheques": 0, "start_months": -5, "route": "self"},
    {"building": "binmahmoud", "unit": "2B", "tenant": "Deepak Sharma", "qid": "28999300645", "mobile": "+974 7723 1108", "rent": 7000, "deposit": 7000, "mode": "Cheque", "cheques": 12, "start_months": -5, "route": "self", "bank": "Commercial Bank of Qatar", "first_cheque": "903442"},
    {"building": "binmahmoud", "unit": "3A", "tenant": "Chen Wei", "qid": "29233500890", "mobile": "+974 5541 9963", "rent": 5900, "deposit": 5900, "mode": "Cheque", "cheques": 12, "start_months": -2, "route": "pending", "bank": "Qatar National Bank", "first_cheque": "411903"},

    # -- Al Sadd Court ----------------------------------------------------
    {"building": "alsadd", "unit": "S1", "tenant": "Doha Fresh Mart W.L.L.", "corporate": True, "cr_no": "CR-64188", "qid": "CR-64188", "mobile": "+974 4433 2211", "rent": 12000, "deposit": 24000, "mode": "Cheque", "cheques": 12, "start_months": -4, "route": "self", "bank": "Doha Bank", "first_cheque": "780660"},
    {"building": "alsadd", "unit": "1", "tenant": "Yusuf Abdelrahman", "qid": "28688100376", "mobile": "+974 3355 7702", "rent": 9500, "deposit": 9500, "mode": "Cheque", "cheques": 12, "start_months": -4, "route": "self", "bank": "Qatar National Bank", "first_cheque": "412201"},
    {"building": "alsadd", "unit": "2", "tenant": "Lakshmi Iyer", "qid": "29077800459", "mobile": "+974 7766 0084", "rent": 9200, "deposit": 9200, "mode": "Cheque", "cheques": 12, "start_months": -3, "route": "self", "bank": "Commercial Bank of Qatar", "first_cheque": "903990"},
]


# Units left without a tenancy, and the state they sit in. This is where void
# days come from, so it is deliberate rather than incidental.
VACANCIES = {
    "Najma Tower-402": "Vacant",
    "Najma Tower-602": "Under Maintenance",
    "Bin Mahmoud Residency-3B": "Vacant",
    "Al Sadd Court-3": "Not Ready",
}


# ---------------------------------------------------------------- maintenance

JOBS = [
    {"building": "Najma Tower", "unit": "Najma Tower-602", "category": "Air Conditioning",
     "priority": "Emergency", "issue": "Split unit compressor failed",
     "description": "Compressor seized in the living room split. Unit is unlettable until replaced.",
     "cost": 3500, "advance": ["Assigned"]},
    {"building": "Najma Tower", "unit": "Najma Tower-301", "category": "Plumbing",
     "priority": "High", "issue": "Bathroom leak into 201 ceiling",
     "description": "Water tracking down through the slab into the unit below.",
     "cost": 850, "advance": ["Assigned", "In Progress"]},
    {"building": "Bin Mahmoud Residency", "unit": "Bin Mahmoud Residency-2B",
     "category": "Electrical", "priority": "Medium",
     "issue": "Kitchen socket ring dead",
     "description": "Tenant reports no power to the kitchen sockets.",
     "cost": 420, "advance": ["Assigned", "In Progress", "Resolved"],
     "rechargeable": True, "recharge_amount": 420,
     "recharge_to": "Deepak Sharma"},
    {"building": "Al Sadd Court", "unit": "Al Sadd Court-S1", "category": "Civil",
     "priority": "Medium", "issue": "Shopfront glazing cracked",
     "description": "Impact crack to the left pane. Not yet unsafe.",
     "cost": 1200, "advance": ["Scheduled"]},
    {"building": "Najma Tower", "unit": None, "category": "Lift",
     "priority": "High", "issue": "Lift annual inspection overdue",
     "description": "Preventive. Contract inspection has slipped a month.",
     "cost": 1800, "advance": ["Assigned"], "preventive": True},
]


# ------------------------------------------------------------------ documents

DOCUMENTS = [
    {"type": "QID", "party_type": "Customer", "party": "Rajesh Kumar Nair",
     "document_no": "28912400177", "issue_months": -22, "expiry_months": 14,
     "confirm": True},
    {"type": "QID", "party_type": "Customer", "party": "Elena Petrova",
     "document_no": "29208800257", "issue_months": -23, "expiry_months": 1,
     "confirm": True},
    {"type": "QID", "party_type": "Customer", "party": "Deepak Sharma",
     "document_no": "28999300645", "issue_months": -24, "expiry_months": 0,
     "confirm": True},
    {"type": "Commercial Registration", "party_type": "Customer",
     "party": "Gulf Horizon Trading W.L.L.", "document_no": "CR-91277",
     "issue_months": -14, "expiry_months": 10, "confirm": True},
    {"type": "Head Lease", "party_type": "Supplier",
     "party": "Abdulla Nasser Al-Mannai", "building": "Najma Tower",
     "document_no": "HL-NAJMA-SIGNED", "issue_months": -10, "confirm": True},
    {"type": "Head Lease", "party_type": "Supplier",
     "party": "Al Rayyan Properties W.L.L.", "building": "Bin Mahmoud Residency",
     "document_no": "HL-BMR-SIGNED", "issue_months": -8, "confirm": True},
    {"type": "Tenancy Agreement", "party_type": "Customer",
     "party": "Yusuf Abdelrahman", "building": "Al Sadd Court",
     "unit": "Al Sadd Court-1", "document_no": "TA-SIGNED-ALSADD-1",
     "issue_months": -4, "confirm": True},
    {"type": "Utility Bill", "building": "Najma Tower",
     "document_no": "KM-INV-889201", "issue_months": -1, "confirm": True},
    {"type": "Bank Statement", "document_no": "QNB-STMT-PREV",
     "issue_months": -1, "confirm": False},
    {"type": "Passport", "party_type": "Customer", "party": "Chen Wei",
     "document_no": "EK7712008", "issue_months": -40, "expiry_months": 62,
     "reject": "Scan is unreadable on pages 2 and 3. Re-scan needed."},
]


# A QID that was renewed. The old one is registered and confirmed first, then
# the new one, which should supersede it.
SUPERSESSION = {
    "party": "Kiran Prasad",
    "old": {"document_no": "28811200962", "issue_months": -25, "expiry_months": -1},
    "new": {"document_no": "28811200962", "issue_months": -1, "expiry_months": 23},
}
