app_name = "darkbrown"
app_title = "DarkBrown"
app_publisher = "DarkBrown RealEstate"
app_description = "Dark Brown Real Estate — MD dashboard and custom tooling"
app_email = "admin@darkbrown.qa"
app_license = "MIT"

# ════════════════════════════════════════════════════════════════
# ADD THESE LINES TO YOUR EXISTING darkbrown/hooks.py
# (do not replace the whole file — just add/merge these two hooks)
# ════════════════════════════════════════════════════════════════

# Inject branded login styling + layout into website/portal pages
# (this is where /login is rendered). NOT app_include_* — that's the desk.

web_include_css = [
    "/assets/darkbrown/css/darkbrown_login.css",
]

web_include_js = [
    "/assets/darkbrown/js/darkbrown_login.js",
]

# If your hooks.py ALREADY has web_include_css / web_include_js defined,
# don't add a second copy — instead append the new path to the existing
# list, e.g.:
#
# web_include_css = [
#     "/assets/darkbrown/css/something_existing.css",
#     "/assets/darkbrown/css/darkbrown_login.css",   # <-- add this line
# ]
