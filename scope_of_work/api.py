# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whitelisted methods behind the Scope of Work form's buttons."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

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
	elif kind == "pdf":
		from scope_of_work import printing

		content, file_name, kind_type = printing.pdf(doc), printing.PDF_NAME.format(name=doc.name), "application/pdf"
	elif kind == "md":
		content, file_name, kind_type = t.markdown(tree), scope.MD_NAME.format(name=doc.name), "text/markdown"
	else:
		frappe.throw(_("Unknown download: {0}").format(kind))
	frappe.response.filename = file_name
	frappe.response.filecontent = content if isinstance(content, bytes) else content.encode()
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


@frappe.whitelist()
def add_package(name: str, package: str) -> list[str]:
	doc = _scope(name)
	added = scope.add_package(doc, package)
	doc.save()
	return added


@frappe.whitelist()
def suggestions(name: str) -> list[dict]:
	return scope.suggestions(_scope(name, write=False))


@frappe.whitelist()
def record_revision(name: str) -> str:
	return scope.record_revision(_scope(name))


@frappe.whitelist()
def make_project(name: str) -> str:
	frappe.has_permission("Project", "create", throw=True)
	frappe.has_permission("Task", "create", throw=True)
	return scope.make_project(_scope(name))


@frappe.whitelist()
def make_subscription(name: str, start_date: str | None = None) -> str:
	frappe.has_permission("Subscription", "create", throw=True)
	return scope.make_subscription(_scope(name), start_date)


@frappe.whitelist()
def file_to_nextcloud(name: str) -> dict:
	from scope_of_work import filing

	return filing.file_scope(_scope(name))


@frappe.whitelist()
def share_with_client(name: str) -> str:
	return scope.share_with_client(_scope(name))


@frappe.whitelist()
def revoke_client_link(name: str) -> None:
	scope.revoke_client_link(_scope(name))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=60 * 60)
def client_opt_in(key: str, ids: str) -> list[str]:
	"""The client's page saves its ticks here. The key is the only access; a locked scope refuses."""
	from scope_of_work.www.scope import LOCKED, find

	doc = find(key)
	if doc is None:
		frappe.throw(_("This link is not valid any more."), frappe.PermissionError)
	if doc.status in LOCKED:
		frappe.throw(_("This scope is {0} and can no longer be changed here.").format(_(doc.status).lower()))
	chosen = json.loads(ids)
	if not isinstance(chosen, list) or not all(isinstance(i, str) for i in chosen):
		frappe.throw(_("Bad request."))
	return scope.apply_client_choice(doc, chosen)
