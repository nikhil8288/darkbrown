app_name = "darkbrown"
app_title = "DarkBrown"
app_publisher = "DarkBrown RealEstate"
app_description = "Dark Brown Real Estate — MD dashboard and custom tooling"
app_email = "admin@darkbrown.qa"
app_license = "MIT"

on_session_creation = "darkbrown.auth.on_session_creation"

doc_events = {
    "Building": {
        "after_insert": "darkbrown.darkbrown.utils.cost_center.create_building_cost_center",
        "on_update": "darkbrown.darkbrown.utils.cost_center.sync_building_cost_center_rename",
        "on_trash": "darkbrown.darkbrown.utils.cost_center.handle_building_cost_center_delete",
    }
}
