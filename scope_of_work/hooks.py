# SPDX-License-Identifier: AGPL-3.0-or-later
from . import __version__ as _version

app_name = "scope_of_work"
app_title = "Scope of Work"
app_publisher = "Zephyrex Technologies Limited"
app_description = "Per-client scopes of work as tech trees, built from a catalogue of billable ERPNext items"
app_email = "jameson@zephyrex.ca"
app_license = "AGPL-3.0-or-later"
app_version = _version

required_apps = ["frappe", "erpnext"]

# The catalogue lives on Item and Item Group; the fields are created (and kept current) by the app.
after_install = "scope_of_work.install.ensure_fields"
after_migrate = "scope_of_work.install.ensure_fields"

# The print format renders the scope through this method.
jinja = {"methods": ["scope_of_work.printing.scope_html"]}
