# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import a scope written elsewhere (one JSON document) as catalogue Items plus a client's Scope of Work.

Shape (every key but the marked ones is optional)::

    {
      "parent_item_group": "All Item Groups",
      "uom": "Nos",
      "branches": [{"letter": "W", "name": "Web", "colour": "#2f6fb3", "order": 2}],          # required
      "items": [                                                                              # required
        {"code": "SOW Web Store", "id": "W4", "name": "Online store", "branch": "W",
         "requires": ["W1", "I1"], "any_of": [], "is_choice": false, "choice_of": "",
         "later": false, "required": false, "charge": "One-time" | "Per month",
         "delivers": ["…"], "acceptance": "…", "note": "…", "provides": "…",
         "requested": false, "recommended": false, "reason": "", "opted_in": false,
         "default_option": false}
      ],
      "scope": {"title": "…", "party_type": "Customer" | "Lead" | "Prospect", "party": "…",   # required
                "prepared_for": "…", "company": "…", "price_list": "…", "date": "YYYY-MM-DD",
                "intro": "…", "provides_general": "…", "exclusions": ["…"], "assumptions": ["…"],
                "changes": ["…"], "open_points": ["…"], "payment_terms": "…", "signatory": "…"}
    }

Prerequisites name item IDs (as in the source scope), not item codes, and the IDs are kept. A catalogue Item
that already exists is left as it is (its wording on the scope row still comes from the file); a branch's Item
Group is created if missing and its letter, colour and order are set.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from scope_of_work import tree as t


def import_scope(data: dict[str, Any]) -> str:
	items = data["items"]
	by_id = {item["id"]: item for item in items}
	groups = {
		b["letter"]: ensure_branch(b, data.get("parent_item_group") or "All Item Groups") for b in data["branches"]
	}
	for item in items:
		if item["branch"] not in groups:
			frappe.throw(_("{0} is in branch {1}, which the file does not define.").format(item["id"], item["branch"]))
	uom = data.get("uom") or "Nos"
	for item in prerequisites_first(items, by_id):
		ensure_item(item, by_id, groups[item["branch"]], uom)
	scope = data["scope"]
	doc = frappe.get_doc(
		{
			"doctype": "Scope of Work",
			"title": scope["title"],
			"party_type": scope.get("party_type") or "Customer",
			"party": scope["party"],
			"prepared_for": scope.get("prepared_for"),
			"company": scope.get("company") or frappe.defaults.get_user_default("Company"),
			"price_list": scope.get("price_list")
			or frappe.db.get_single_value("Selling Settings", "selling_price_list"),
			"date": scope.get("date") or frappe.utils.today(),
			"signatory": scope.get("signatory"),
			"intro": scope.get("intro"),
			"provides_general": scope.get("provides_general"),
			"exclusions": "\n".join(scope.get("exclusions") or []),
			"assumptions": "\n".join(scope.get("assumptions") or []),
			"changes": "\n".join(scope.get("changes") or []),
			"open_points": "\n".join(scope.get("open_points") or []),
			"payment_terms": scope.get("payment_terms"),
			"provides": [{"items": item["id"], "provides": item["provides"]} for item in items if item.get("provides")],
			"items": [row(item, groups[item["branch"]]) for item in items],
		}
	)
	doc.insert()
	return doc.name


def prerequisites_first(items: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
	"""Items ordered so each comes after the items it links to (its prerequisites and its choice group)."""
	done: dict[str, dict[str, Any]] = {}

	def visit(item: dict[str, Any], path: tuple[str, ...]) -> None:
		if item["id"] in done:
			return
		if item["id"] in path:
			frappe.throw(_("Prerequisites go round in a circle at {0}.").format(item["id"]))
		links = list(item.get("requires") or []) + list(item.get("any_of") or [])
		if item.get("choice_of"):
			links.append(item["choice_of"])
		for eid in links:
			if eid not in by_id:
				frappe.throw(_("{0} requires {1}, which is not in the file.").format(item["id"], eid))
			visit(by_id[eid], (*path, item["id"]))
		done[item["id"]] = item

	for item in items:
		visit(item, ())
	return list(done.values())


def row(item: dict[str, Any], group: str) -> dict[str, Any]:
	return {
		"scope_id": item["id"],
		"item_code": item["code"],
		"item_name": item["name"],
		"branch": group,
		"requires": ", ".join(item.get("requires") or []),
		"any_of": ", ".join(item.get("any_of") or []),
		"is_choice_group": int(bool(item.get("is_choice"))),
		"choice_of": item.get("choice_of") or "",
		"default_option": int(bool(item.get("default_option"))),
		"later": int(bool(item.get("later"))),
		"required": int(bool(item.get("required"))),
		"charge": item.get("charge") or t.ONE_TIME,
		"requested": int(bool(item.get("requested"))),
		"recommended": int(bool(item.get("recommended"))),
		"reason": item.get("reason") or "",
		"opted_in": int(bool(item.get("opted_in"))),
		"delivers": "\n".join(item.get("delivers") or []),
		"acceptance": item.get("acceptance") or "",
		"note": item.get("note") or "",
	}


def ensure_branch(branch: dict[str, Any], parent: str) -> str:
	name = branch.get("item_group") or branch["name"]
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent}).insert()
	frappe.db.set_value(
		"Item Group",
		name,
		{
			"scope_branch_letter": branch["letter"],
			"scope_branch_label": branch["name"],
			"scope_branch_colour": branch.get("colour") or "",
			"scope_branch_order": branch.get("order") or 0,
		},
	)
	return name


def ensure_item(item: dict[str, Any], by_id: dict[str, dict[str, Any]], group: str, uom: str) -> None:
	if frappe.db.exists("Item", item["code"]):
		return

	def code(eid: str) -> str:
		if eid not in by_id:
			frappe.throw(_("{0} requires {1}, which is not in the file.").format(item["id"], eid))
		return by_id[eid]["code"]

	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item["code"],
			"item_name": item["name"],
			"item_group": group,
			"stock_uom": uom,
			"is_stock_item": 0,
			"is_sales_item": 0 if item.get("is_choice") else 1,
			"scope_enabled": 1,
			"scope_is_choice_group": int(bool(item.get("is_choice"))),
			"scope_choice_group": code(item["choice_of"]) if item.get("choice_of") else None,
			"scope_later": int(bool(item.get("later"))),
			"scope_required": int(bool(item.get("required"))),
			"scope_charge": item.get("charge") or t.ONE_TIME,
			"scope_requires": [{"requirement": code(r)} for r in item.get("requires") or []]
			+ [{"requirement": code(r), "any_of": 1} for r in item.get("any_of") or []],
			"scope_delivers": "\n".join(item.get("delivers") or []),
			"scope_acceptance": item.get("acceptance") or "",
			"scope_note": item.get("note") or "",
			"scope_provides": item.get("provides") or "",
		}
	).insert()
