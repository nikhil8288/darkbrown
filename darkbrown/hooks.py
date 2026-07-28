app_name = "darkbrown"
app_title = "DarkBrown"
app_publisher = "DarkBrown RealEstate"
app_description = "DarkBrown Real Estate — V2 property management platform"
app_email = "admin@darkbrown.qa"
app_license = "MIT"

required_apps = ["erpnext"]

# Built and validated against Frappe/ERPNext v15.
required_frappe_version = ">=15.0.0"

after_install = "darkbrown.install.after_install"
after_migrate = "darkbrown.install.after_migrate"

# The prototype is the application. Frappe's desk stays reachable at /app for
# Administrator only; every business role lands on the prototype.
page_renderer = ["darkbrown.renderer.DarkBrownApp"]

home_page = "darkbrown"
role_home_page = {
    "Managing Director": "darkbrown",
    "General Manager": "darkbrown",
    "Accounts": "darkbrown",
    "Documentation": "darkbrown",
    "Maintenance": "darkbrown",
}

# ---------------------------------------------------------------- doc events
doc_events = {
    "Building": {
        "after_insert": "darkbrown.utils.cost_center.create_building_cost_center",
        "on_update": "darkbrown.utils.cost_center.sync_building_cost_center",
        "after_rename": "darkbrown.utils.cost_center.sync_after_rename",
        "on_trash": "darkbrown.utils.cost_center.guard_cost_center_delete",
    },
    "Payment Entry": {
        "on_submit": "darkbrown.utils.reconciliation.on_payment_submit",
        "on_cancel": "darkbrown.utils.reconciliation.on_payment_cancel",
    },
}

# ---------------------------------------------------------------- scheduler
scheduler_events = {
    "daily_long": [
        "darkbrown.utils.collections_case.nightly",
        "darkbrown.utils.cheques.nightly",
    ],
    "cron": {
        # 07:00 Doha, on the configured generation day only
        "0 4 * * *": [
            "darkbrown.utils.rent_invoicing.monthly_reminder",
        ],
    },
}

# ---------------------------------------------------------------- fixtures
fixtures = [
    {
        "dt": "Role",
        "filters": [["name", "in", [
            "Managing Director",
            "General Manager",
            "Accounts",
            "Documentation",
            "Maintenance",
        ]]],
    },
    {
        "dt": "Custom Field",
        "filters": [["module", "=", "Darkbrown"]],
    },
]

# ---------------------------------------------------------------- permissions
permission_query_conditions = {
    "Building": "darkbrown.permissions.building_query",
    "Unit": "darkbrown.permissions.unit_query",
}
