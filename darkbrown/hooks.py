app_name = "darkbrown"
app_title = "DarkBrown"
app_publisher = "DarkBrown RealEstate"
app_description = "DarkBrown Real Estate — V2 property management platform"
app_email = "admin@darkbrown.qa"
app_license = "MIT"

required_apps = ["erpnext"]

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
after_install = "darkbrown.install.after_install"

# ---------------------------------------------------------------------------
# Document events
#
# Wave 1 only. Agreement, document, invoicing, cheque, case, move-out,
# maintenance and utilities hooks are added by their own waves.
# ---------------------------------------------------------------------------
doc_events = {
    "Building": {
        "after_insert": "darkbrown.utils.cost_center.create_building_cost_center",
        "on_update": "darkbrown.utils.cost_center.sync_building_cost_center",
        "after_rename": "darkbrown.utils.cost_center.sync_after_rename",
        "on_trash": "darkbrown.utils.cost_center.guard_cost_center_delete",
    },
}

scheduler_events = {}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
fixtures = [
    {"dt": "Role", "filters": [["name", "in", [
        "Managing Director",
        "General Manager",
        "Accounts",
        "Documentation",
        "Maintenance",
    ]]]},
]
