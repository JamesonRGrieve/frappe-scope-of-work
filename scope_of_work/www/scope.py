# SPDX-License-Identifier: AGPL-3.0-or-later
"""The client's page for a scope: /scope?key=<the scope's client key>. No login; the key is the access."""

from __future__ import annotations

import frappe
from frappe.utils import fmt_money
from markupsafe import Markup

from scope_of_work import scope as sow
from scope_of_work import tree as t

no_cache = 1
LOCKED = ("Accepted", "Withdrawn")


def find(key: str | None):
	if not key or len(key) < 20:
		return None
	name = frappe.db.get_value("Scope of Work", {"client_key": key})
	return frappe.get_doc("Scope of Work", name) if name else None


def meta(e: t.Entry, requires: str) -> str:
	parts = []
	if e.required and not e.choice_of:
		parts.append("Required")
	elif e.delivered:
		parts.append("Already delivered")
	elif e.later:
		parts.append("Later: not priced yet")
	if requires and requires != "none":
		parts.append(f"needs {requires}")
	if e.reason:
		parts.append(e.reason)
	return " · ".join(parts)


def get_context(context):
	context.no_cache = 1
	doc = find(frappe.form_dict.get("key"))
	if doc is None:
		context.missing = True
		context.title = "Scope of work"
		return context
	tree = sow.build(doc)
	settings = frappe.get_cached_doc("Scope of Work Settings")
	currency = doc.currency or ""
	items = []
	order = {b.letter: n for n, b in enumerate(tree.scope.branches)}
	ordered = tree.ordered()
	position = {e.id: n for n, e in enumerate(ordered)}
	# Group by branch for the client, keeping tree order inside a branch (options stay under their group).
	ordered.sort(
		key=lambda e: (
			order.get(e.branch, 99),
			position[e.choice_of] if e.choice_of else position[e.id],
			position[e.id],
		)
	)
	for e in ordered:
		items.append(
			{
				"id": e.id,
				"name": e.name,
				"branch": tree.branches[e.branch].name,
				"colour": tree.branches[e.branch].colour,
				"stack": e.stack,
				"requires": e.requires,
				"any_of": e.any_of,
				"choice_of": e.choice_of,
				"is_choice": e.is_choice,
				"group_required": bool(e.choice_of and tree.by_id[e.choice_of].required),
				"default_option": e.default_option,
				"required": e.required and not e.choice_of,
				"later": e.later,
				"delivered": e.delivered,
				"checked": bool(e.opted_in or (e.required and not e.choice_of)),
				"requested": e.requested,
				"recommended": e.recommended,
				"reason": e.reason,
				"rate": float(e.rate or 0),
				"price": fmt_money(float(e.rate), currency=currency) if e.rate else "TBS",
				"charge": e.charge,
				"delivers": e.delivers,
				"acceptance": e.acceptance,
				"note": e.note,
				"requires_text": t.requires_text(e) if not e.choice_of else "",
				"meta": meta(e, t.requires_text(e) if not e.choice_of else ""),
			}
		)
	context.update(
		{
			"title": doc.title,
			"doc": doc,
			"key": frappe.form_dict.get("key"),
			"prepared_for": doc.prepared_for or sow.party_display(doc),
			"company": doc.company,
			"intro": settings.client_page_intro or "",
			"drawing": Markup(t.svg(tree)),
			"items": items,
			"currency": currency,
			"locked": doc.status in LOCKED,
			"status": doc.status,
		}
	)
	return context
