# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scope catalogue is ERPNext's own billable Items: these fields add the tree to Item and Item Group."""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CHARGE = "One-time\nPer month"

ITEM_FIELDS = [
	{"fieldname": "scope_tab", "fieldtype": "Tab Break", "label": "Scope of Work", "insert_after": "dashboard_tab"},
	{
		"fieldname": "scope_enabled",
		"fieldtype": "Check",
		"label": "In the scope catalogue",
		"insert_after": "scope_tab",
		"description": "Offer this item on scopes of work. Its Item Group is its branch.",
	},
	{
		"fieldname": "scope_is_choice_group",
		"fieldtype": "Check",
		"label": "Choice group",
		"insert_after": "scope_enabled",
		"depends_on": "scope_enabled",
		"description": "A slot whose options are other catalogue items; exactly one is taken. Not itself charged.",
	},
	{
		"fieldname": "scope_choice_group",
		"fieldtype": "Link",
		"options": "Item",
		"label": "Option of",
		"insert_after": "scope_is_choice_group",
		"depends_on": "eval:doc.scope_enabled && !doc.scope_is_choice_group",
	},
	{
		"fieldname": "scope_later",
		"fieldtype": "Check",
		"label": "Later item (on the tree, not priced)",
		"insert_after": "scope_choice_group",
		"depends_on": "scope_enabled",
	},
	{
		"fieldname": "scope_required",
		"fieldtype": "Check",
		"label": "Required on every scope",
		"insert_after": "scope_later",
		"depends_on": "scope_enabled",
	},
	{
		"fieldname": "scope_charge",
		"fieldtype": "Select",
		"options": CHARGE,
		"default": "One-time",
		"label": "Charged",
		"insert_after": "scope_required",
		"depends_on": "scope_enabled",
	},
	{
		"fieldname": "scope_stack",
		"fieldtype": "Link",
		"options": "Scope Stack Component",
		"label": "Proposed stack component",
		"insert_after": "scope_charge",
		"depends_on": "eval:doc.scope_enabled && !doc.scope_is_choice_group",
		"mandatory_depends_on": "eval:doc.scope_enabled && !doc.scope_is_choice_group",
		"description": "What the item is built on (ERPNext, WordPress, Proxmox, OPNsense…); shown in its box on the drawing.",
	},
	{
		"fieldname": "scope_column_break",
		"fieldtype": "Column Break",
		"insert_after": "scope_stack",
	},
	{
		"fieldname": "scope_requires",
		"fieldtype": "Table",
		"options": "Scope Item Requirement",
		"label": "Requires",
		"insert_after": "scope_column_break",
		"depends_on": "eval:doc.scope_enabled && !doc.scope_choice_group",
	},
	{
		"fieldname": "scope_text_section",
		"fieldtype": "Section Break",
		"label": "Scope wording",
		"insert_after": "scope_requires",
		"depends_on": "scope_enabled",
	},
	{
		"fieldname": "scope_delivers",
		"fieldtype": "Long Text",
		"label": "Delivers",
		"insert_after": "scope_text_section",
		"description": "One point per line, in the client's words, with the facts that fix the size.",
	},
	{
		"fieldname": "scope_acceptance",
		"fieldtype": "Small Text",
		"label": "Acceptance",
		"insert_after": "scope_delivers",
		"description": "One sentence: a demonstration on the client's own system that either happens or does not.",
	},
	{
		"fieldname": "scope_note",
		"fieldtype": "Small Text",
		"label": "Note",
		"insert_after": "scope_acceptance",
		"description": "Only for a dependency outside our control, and what happens if it fails.",
	},
	{
		"fieldname": "scope_provides",
		"fieldtype": "Small Text",
		"label": "The client provides",
		"insert_after": "scope_note",
	},
]

ITEM_GROUP_FIELDS = [
	{
		"fieldname": "scope_branch_section",
		"fieldtype": "Section Break",
		"label": "Scope of Work branch",
		"insert_after": "is_group",
		"collapsible": 1,
	},
	{
		"fieldname": "scope_branch_letter",
		"fieldtype": "Data",
		"length": 1,
		"label": "Branch letter",
		"insert_after": "scope_branch_section",
		"description": "One capital letter; item IDs in this branch start with it. X is kept for later items.",
	},
	{
		"fieldname": "scope_branch_label",
		"fieldtype": "Data",
		"label": "Branch name",
		"insert_after": "scope_branch_letter",
		"description": "The name printed on scopes; empty uses the Item Group's name.",
	},
	{
		"fieldname": "scope_branch_colour",
		"fieldtype": "Color",
		"label": "Branch colour",
		"insert_after": "scope_branch_label",
	},
	{
		"fieldname": "scope_branch_order",
		"fieldtype": "Int",
		"label": "Branch order",
		"insert_after": "scope_branch_colour",
		"description": "Lower comes first in the drawing's legend and the document.",
	},
]


def ensure_fields() -> None:
	create_custom_fields({"Item": ITEM_FIELDS, "Item Group": ITEM_GROUP_FIELDS}, update=True)
