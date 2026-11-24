# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whitelisted methods behind the Scope of Work form's buttons."""

from __future__ import annotations

import json

import frappe
from frappe import _

from scope_of_work import scope
from scope_of_work import tree as t


def _scope(name: str, write: bool = True):
	doc = frappe.get_doc("Scope of Work", name)
	doc.check_permission("write" if write else "read")
	return doc


@frappe.whitelist()
def add_items(name: str, item_codes: str | list, requested: int = 0, recommended: int = 0) -> list[str]:
	codes = json.loads(item_codes) if isinstance(item_codes, str) else item_codes
	doc = _scope(name)
	added = scope.add_items(doc, codes, requested=bool(int(requested)), recommended=bool(int(recommended)))
	doc.save()
	return added


@frappe.whitelist()
def refresh_rates(name: str) -> int:
	doc = _scope(name)
	changed = scope.refresh_rates(doc)
	doc.save()
	return changed


@frappe.whitelist()
def opt_in_highlights(name: str) -> list[str]:
	doc = _scope(name)
	ticked = scope.opt_in_highlights(doc)
	doc.save()
	return ticked


@frappe.whitelist()
def preview(name: str) -> str:
	return t.svg(scope.build(_scope(name, write=False)))


@frappe.whitelist()
def download(name: str, kind: str) -> None:
	doc = _scope(name, write=False)
	tree = scope.build(doc)
	if kind == "svg":
		content, file_name, kind_type = t.svg(tree), scope.SVG_NAME.format(name=doc.name), "image/svg+xml"
	elif kind == "md":
		content, file_name, kind_type = t.markdown(tree), scope.MD_NAME.format(name=doc.name), "text/markdown"
	else:
		frappe.throw(_("Unknown download: {0}").format(kind))
	frappe.response.filename = file_name
	frappe.response.filecontent = content.encode()
	frappe.response.type = "download"
	frappe.response.content_type = kind_type


@frappe.whitelist()
def attach_files(name: str) -> dict[str, str]:
	return scope.attach_files(_scope(name))


@frappe.whitelist()
def make_drafts(name: str) -> dict[str, str | None]:
	doc = _scope(name)
	frappe.has_permission("Quotation", "create", throw=True)
	if doc.party_type == "Customer":
		frappe.has_permission("Contract", "create", throw=True)
	return scope.make_drafts(doc)


@frappe.whitelist(methods=["POST"])
def import_scope(data: str | dict) -> str:
	"""Import a scope from one JSON document (shape in importer.py). Needs Item and Item Group create rights for
	new catalogue items, and Scope of Work create rights."""
	from scope_of_work import importer

	frappe.has_permission("Scope of Work", "create", throw=True)
	return importer.import_scope(json.loads(data) if isinstance(data, str) else data)
