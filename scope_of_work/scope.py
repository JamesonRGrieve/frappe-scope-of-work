# SPDX-License-Identifier: AGPL-3.0-or-later
"""Between the DocTypes and the tree: copy catalogue Items into a client's scope, read a scope as a `tree.Tree`,
and make the draft Quotation and Contract from it. Nothing here submits a document."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, formatdate, md_to_html

from scope_of_work import tree as t

FROZEN = ("Sent", "Accepted")
SVG_NAME = "{name} tree.svg"
MD_NAME = "{name} scope.md"
DEFAULT_COLOUR = "#5b6b7a"


def split_ids(text: str | None) -> list[str]:
	return [part for part in re.split(r"[\s,]+|\bor\b", text or "") if part]


def lines(text: str | None) -> list[str]:
	return [line.strip() for line in (text or "").splitlines() if line.strip()]


# ---- the catalogue


def catalogue_item(code: str) -> Any:
	item = frappe.get_cached_doc("Item", code)
	if not item.get("scope_enabled"):
		frappe.throw(
			_("{0} is not in the scope catalogue (Item → Scope of Work → In the scope catalogue).").format(code)
		)
	return item


def branch_of(group: str) -> t.Branch:
	letter, colour, label, name = frappe.get_cached_value(
		"Item Group", group, ["scope_branch_letter", "scope_branch_colour", "scope_branch_label", "item_group_name"]
	)
	if not letter or not re.fullmatch(r"[A-Z]", letter) or letter == t.LATER_LETTER:
		frappe.throw(
			_("Item Group {0} needs a branch letter (one capital letter other than X) to hold scope items.").format(
				group
			)
		)
	return t.Branch(letter, label or name, colour or DEFAULT_COLOUR)


def with_prerequisites(codes: list[str]) -> list[str]:
	"""The items asked for, everything they need, and for a choice group (or one of its options) the whole group."""
	seen: list[str] = []

	def visit(code: str) -> None:
		if code in seen:
			return
		item = catalogue_item(code)
		if item.get("scope_choice_group"):
			visit(item.scope_choice_group)
			if code in seen:
				return
		for req in item.get("scope_requires") or []:
			visit(req.requirement)
		seen.append(code)
		if item.get("scope_is_choice_group"):
			for option in frappe.get_all(
				"Item",
				filters={"scope_choice_group": code, "scope_enabled": 1, "disabled": 0},
				pluck="name",
				order_by="creation asc, name asc",
			):
				visit(option)

	for code in codes:
		visit(code)
	return seen


def add_items(doc: Any, codes: list[str], requested: bool = False, recommended: bool = False) -> list[str]:
	"""Copy catalogue items (with their prerequisites) into the scope, giving each new row the next free ID.

	Returns the IDs of the rows added. Items already on the scope are left as they are, apart from the
	requested/recommended flags, which are set on the items named (not on the prerequisites pulled in)."""
	by_code = {row.item_code: row for row in doc.items}
	used = {row.scope_id for row in doc.items}
	added = []
	for code in with_prerequisites(codes):
		row = by_code.get(code)
		if row is None:
			item = catalogue_item(code)
			branch = branch_of(item.item_group)
			if item.get("scope_choice_group"):
				group_row = by_code[item.scope_choice_group]
				scope_id = t.next_id(used, "", option_of=group_row.scope_id)
			else:
				scope_id = t.next_id(used, t.LATER_LETTER if item.get("scope_later") else branch.letter)
			requires = [r.requirement for r in item.get("scope_requires") or [] if not r.any_of]
			any_of = [r.requirement for r in item.get("scope_requires") or [] if r.any_of]
			row = doc.append(
				"items",
				{
					"scope_id": scope_id,
					"item_code": code,
					"item_name": item.item_name,
					"branch": item.item_group,
					"stack": item.get("scope_stack") or "",
					"requires": ", ".join(by_code[c].scope_id for c in requires),
					"any_of": ", ".join(by_code[c].scope_id for c in any_of),
					"is_choice_group": item.get("scope_is_choice_group") or 0,
					"choice_of": by_code[item.scope_choice_group].scope_id if item.get("scope_choice_group") else "",
					"later": item.get("scope_later") or 0,
					"required": item.get("scope_required") or 0,
					"charge": item.get("scope_charge") or t.ONE_TIME,
					"rate": 0 if item.get("scope_is_choice_group") or item.get("scope_later") else price_of(doc, code),
					"delivers": item.get("scope_delivers") or "",
					"acceptance": item.get("scope_acceptance") or "",
					"note": item.get("scope_note") or "",
				},
			)
			by_code[code] = row
			used.add(scope_id)
			added.append(scope_id)
			if item.get("scope_provides"):
				doc.append("provides", {"items": scope_id, "provides": item.scope_provides})
		if code in codes:
			row.requested = row.requested or int(requested)
			row.recommended = row.recommended or int(recommended)
	return added


def price_of(doc: Any, code: str) -> float:
	"""The item's price on the scope's price list; zero (printed TBS) when there is none. Never inferred."""
	if not doc.price_list:
		return 0
	return flt(
		frappe.db.get_value(
			"Item Price",
			{"price_list": doc.price_list, "item_code": code, "selling": 1, "customer": ["in", ["", None]]},
			"price_list_rate",
			order_by="valid_from desc",
		)
	)


def refresh_rates(doc: Any) -> int:
	changed = 0
	for row in doc.items:
		if row.is_choice_group or row.later or row.withdrawn:
			continue
		rate = price_of(doc, row.item_code)
		if flt(row.rate) != rate:
			row.rate = rate
			changed += 1
	return changed


def opt_in_highlights(doc: Any) -> list[str]:
	"""Tick Opted in on every requested or recommended item and on the prerequisites they need."""
	rows = {row.scope_id: row for row in doc.items if not row.withdrawn}
	ticked = []

	def tick(scope_id: str) -> None:
		row = rows[scope_id]
		if row.opted_in or row.delivered or row.later:
			return
		if row.is_choice_group:
			options = [r for r in rows.values() if r.choice_of == scope_id]
			if not any(r.opted_in or r.delivered for r in options):
				default = next((r for r in options if r.default_option), None)
				if default:
					tick(default.scope_id)
			return
		row.opted_in = 1
		ticked.append(scope_id)
		if row.choice_of:
			for other in rows.values():
				if other.choice_of == row.choice_of and other is not row:
					other.opted_in = 0
			for parent in split_ids(rows[row.choice_of].requires):
				tick(parent)
			return
		for parent in split_ids(row.requires):
			tick(parent)
		alternatives = split_ids(row.any_of)
		if alternatives and not any(rows[a].opted_in or rows[a].delivered for a in alternatives if a in rows):
			tick(alternatives[0])

	for row in list(rows.values()):
		if (row.requested or row.recommended) and not row.later:
			tick(row.scope_id)
	return ticked


# ---- reading a scope as a tree


def to_scope(doc: Any) -> t.Scope:
	branches: dict[str, tuple[int, t.Branch]] = {}
	entries = []
	for row in doc.items:
		branch = branch_of(row.branch or frappe.get_cached_value("Item", row.item_code, "item_group"))
		order = frappe.get_cached_value("Item Group", row.branch, "scope_branch_order") if row.branch else 0
		branches.setdefault(branch.letter, (order or 0, branch))
		rate = flt(row.rate)
		entries.append(
			t.Entry(
				id=row.scope_id,
				name=row.item_name or row.item_code,
				branch=branch.letter,
				stack=row.stack or "",
				requires=split_ids(row.requires),
				any_of=split_ids(row.any_of),
				delivers=lines(row.delivers),
				acceptance=(row.acceptance or "").strip(),
				note=(row.note or "").strip(),
				later=bool(row.later),
				is_choice=bool(row.is_choice_group),
				choice_of=row.choice_of or "",
				default_option=bool(row.default_option),
				charge=row.charge or t.ONE_TIME,
				rate=Decimal(str(rate)) if rate else None,
				required=bool(row.required),
				requested=bool(row.requested),
				recommended=bool(row.recommended),
				reason=(row.reason or "").strip(),
				opted_in=bool(row.opted_in),
				delivered=bool(row.delivered),
				withdrawn=bool(row.withdrawn),
			)
		)
	ordered = [b for _order, b in sorted(branches.values(), key=lambda ob: (ob[0], ob[1].letter))]
	return t.Scope(
		title=doc.title,
		prepared_for=doc.prepared_for or party_display(doc),
		date=formatdate(doc.date, "yyyy-mm-dd"),
		entries=entries,
		branches=ordered,
		prepared_by=doc.company or "",
		signatory=doc.signatory or "",
		status=doc.status or "Draft",
		currency=doc.currency or "",
		tax_note=doc.tax_note or "before tax",
		intro=(doc.intro or "").strip(),
		provides=[(p.items, p.provides) for p in doc.provides],
		provides_general=(doc.provides_general or "").strip(),
		exclusions=lines(doc.exclusions),
		assumptions=lines(doc.assumptions),
		changes=lines(doc.changes),
		open_points=lines(doc.open_points),
		payment_terms=(doc.payment_terms or "").strip(),
		svg_name=SVG_NAME.format(name=doc.name),
	)


def party_display(doc: Any) -> str:
	if not (doc.party_type and doc.party):
		return ""
	field = {"Customer": "customer_name", "Lead": "company_name", "Prospect": "company_name"}[doc.party_type]
	name = frappe.db.get_value(doc.party_type, doc.party, field)
	if not name and doc.party_type == "Lead":
		name = frappe.db.get_value("Lead", doc.party, "lead_name")
	return name or doc.party


def build(doc: Any) -> t.Tree:
	try:
		return t.Tree(to_scope(doc))
	except t.TreeError as error:
		frappe.throw("<br>".join(frappe.utils.escape_html(p) for p in error.problems), title=_("The tree is broken"))


# ---- documents


def attach_files(doc: Any) -> dict[str, str]:
	"""Write the document and the drawing as attachments of the scope, replacing earlier copies."""
	tree = build(doc)
	files = {MD_NAME.format(name=doc.name): t.markdown(tree), SVG_NAME.format(name=doc.name): t.svg(tree)}
	urls = {}
	for file_name, content in files.items():
		for old in frappe.get_all(
			"File",
			filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "file_name": file_name},
			pluck="name",
		):
			frappe.delete_doc("File", old, ignore_permissions=True)
		saved = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"attached_to_doctype": doc.doctype,
				"attached_to_name": doc.name,
				"content": content,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		urls[file_name] = saved.file_url
	return urls


def quote_rows(tree: t.Tree) -> list[tuple[t.Entry, bool]]:
	"""The Quotation's lines in tree order, as (entry, is_alternative). One per charged item; a choice group
	gives its chosen (or default) option as a normal line with the other options straight beneath it as
	alternatives, which ERPNext leaves out of the total."""
	out = []
	for e in tree.ordered():
		if e.is_choice:
			options = [o for o in tree.options[e.id] if not o.delivered]
			chosen = next((o for o in options if tree.counted(o)), None)
			if chosen is None:
				continue
			out.append((chosen, False))
			out += [(o, True) for o in options if o is not chosen]
		elif not e.choice_of and tree.counted(e):
			out.append((e, False))
	return out


def describe(e: t.Entry) -> str:
	html = "".join(f"<li>{frappe.utils.escape_html(text)}</li>" for text in e.delivers)
	parts = [f"<ul>{html}</ul>"] if html else []
	if e.stack:
		parts.append(f"<p><b>Built on:</b> {frappe.utils.escape_html(e.stack)}</p>")
	if e.acceptance:
		parts.append(f"<p><b>Acceptance:</b> {frappe.utils.escape_html(e.acceptance)}</p>")
	if e.note:
		parts.append(f"<p><b>Note:</b> {frappe.utils.escape_html(e.note)}</p>")
	if e.charge == t.PER_MONTH:
		parts.append("<p>Charged per month.</p>")
	return "".join(parts)


def make_drafts(doc: Any) -> dict[str, str | None]:
	"""A draft Quotation (one line per charged item, named by ID) and, for a Customer, a draft Contract linked to
	it. Both stay drafts for the operator; nothing is submitted. Refuses if either already exists."""
	if doc.quotation or doc.contract:
		frappe.throw(
			_("This scope already has {0}. Delete the drafts first to make new ones.").format(
				", ".join(filter(None, [doc.quotation, doc.contract]))
			)
		)
	tree = build(doc)
	undecided = t.undecided_groups(tree)
	if undecided:
		frappe.throw(
			_("Mark the default option of {0} first: the quote's total is built on it.").format(", ".join(undecided))
		)
	rows = quote_rows(tree)
	if not rows:
		frappe.throw(_("Nothing is opted in or required, so there is nothing to quote."))
	by_id = {row.scope_id: row for row in doc.items}
	quotation = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": doc.party_type,
			"party_name": doc.party,
			"company": doc.company,
			"transaction_date": doc.date,
			"order_type": "Sales",
			"selling_price_list": doc.price_list,
			"currency": doc.currency,
			"items": [
				{
					"item_code": by_id[e.id].item_code,
					"item_name": f"{e.id} {e.name}"[:140],
					"description": describe(e),
					"qty": 1,
					"rate": float(e.rate or 0),
					"price_list_rate": float(e.rate or 0),
					"is_alternative": int(alternative),
				}
				for e, alternative in rows
			],
		}
	)
	quotation.insert()
	contract = None
	if doc.party_type == "Customer":
		contract = frappe.get_doc(
			{
				"doctype": "Contract",
				"party_type": "Customer",
				"party_name": doc.party,
				"start_date": doc.date,
				"contract_terms": md_to_html(t.markdown(tree)),
				"document_type": "Quotation",
				"document_name": quotation.name,
				"requires_fulfilment": 1,
				"fulfilment_terms": [
					{"requirement": f"{e.id} {e.name}"[:140], "notes": e.acceptance}
					for e, alternative in rows
					if not alternative
				],
			}
		).insert()
	doc.db_set({"quotation": quotation.name, "contract": contract.name if contract else None})
	attach_files(doc)
	return {"quotation": quotation.name, "contract": contract.name if contract else None}
