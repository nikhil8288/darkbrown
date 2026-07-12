app_name = "darkbrown"
app_title = "DarkBrown"
app_publisher = "DarkBrown RealEstate"
app_description = "Dark Brown Real Estate — MD dashboard and custom tooling"
app_email = "admin@darkbrown.qa"
app_license = "MIT"

on_session_creation = "darkbrown.auth.on_session_creation"

doc_events = {
    "Building": {
        "after_insert": "darkbrown.utils.cost_center.create_building_cost_center",
        "on_update": "darkbrown.utils.cost_center.sync_building_cost_center_rename",
        "after_rename": "darkbrown.utils.cost_center.sync_building_cost_center_after_rename",
        "on_trash": "darkbrown.utils.cost_center.handle_building_cost_center_delete",
    },
    "Payment Entry": {
        "on_submit": "darkbrown.utils.collections_case.on_payment_entry_submit",
    },
}

scheduler_events = {
    "daily": [
        "darkbrown.utils.collections_case.auto_open_cases",
        "darkbrown.utils.collections_case.reopen_broken_promises",
        "darkbrown.utils.document_register.refresh_statuses",
    ],
    # Frappe "monthly" fires on the 1st day of each month.
    "monthly": [
        "darkbrown.utils.rent_invoicing.generate_monthly_invoices",
    ],
}
