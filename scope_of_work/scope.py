# SPDX-License-Identifier: AGPL-3.0-or-later
"""Between the DocTypes and the tree: copy catalogue Items into a client's scope, read a scope as a `tree.Tree`,
and make the draft Quotation and Contract from it. Nothing here submits a document."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, formatdate, md_to_html, now_datetime

from scope_of_work import revisions
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
					"hours": item.get("scope_hours") or 0,
					"cost": item.get("scope_cost") or 0,
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


def add_package(doc: Any, package: str) -> list[str]:
	"""Add every item of a saved package; its flagged items are marked as recommendations."""
	rows = frappe.get_doc("Scope Package", package).items
	added = add_items(doc, [r.item_code for r in rows if not r.recommended])
	added += add_items(doc, [r.item_code for r in rows if r.recommended], recommended=True)
	return added


def suggestions(doc: Any) -> list[dict[str, Any]]:
	"""Catalogue items that items on the scope are often taken with, and are not on it yet."""
	present = {row.item_code: row.scope_id for row in doc.items if not row.withdrawn}
	out: dict[str, dict[str, Any]] = {}
	for code, scope_id in present.items():
		for suggestion in frappe.get_cached_doc("Item", code).get("scope_suggests") or []:
			if suggestion.item in present or not frappe.db.get_value("Item", suggestion.item, "scope_enabled"):
				continue
			entry = out.setdefault(
				suggestion.item,
				{
					"item_code": suggestion.item,
					"item_name": frappe.get_cached_value("Item", suggestion.item, "item_name"),
					"because": [],
					"reasons": [],
				},
			)
			entry["because"].append(scope_id)
			if suggestion.reason and suggestion.reason not in entry["reasons"]:
				entry["reasons"].append(suggestion.reason)
	return sorted(out.values(), key=lambda e: e["item_code"])


# ---- internal estimate (never printed)


def estimate(doc: Any, tree: t.Tree) -> None:
	"""Row margins, and totals over what the scope charges now (opted-in and required one-time items, a choice
	group's chosen or default option). Items priced below their internal cost are listed."""
	by_id = {row.scope_id: row for row in doc.items}
	price = cost = hours = 0.0
	below = []
	for row in doc.items:
		rate = flt(row.rate)
		row.margin = (rate - flt(row.cost)) / rate * 100 if rate and flt(row.cost) else 0
	for e in tree.entries:
		if not tree.counted(e):
			continue
		row = by_id[e.id]
		hours += flt(row.hours)
		if e.charge == t.ONE_TIME:
			price += flt(row.rate)
			cost += flt(row.cost)
		if flt(row.rate) and flt(row.cost) > flt(row.rate):
			below.append(e.id)
	doc.total_price, doc.total_cost, doc.total_hours = price, cost, hours
	doc.total_margin = (price - cost) / price * 100 if price and cost else 0
	doc.below_cost = ", ".join(below)


# ---- revisions


def recorded(doc: Any) -> list[Any]:
	return frappe.get_all(
		"Scope of Work Revision",
		filters={"scope": doc.name},
		fields=["name", "revision", "snapshot"],
		order_by="revision asc",
	)


def current_snapshot(doc: Any) -> list[dict[str, Any]]:
	return [revisions.snapshot_row(row) for row in doc.items]


def revision_state(doc: Any) -> tuple[int, bool, list[str]]:
	"""(revision to print, whether it is an unsent draft, changes since the revision before it)."""
	if doc.is_new():
		return 0, False, []
	sent = recorded(doc)
	if not sent:
		return 0, False, []
	now = current_snapshot(doc)
	last = json.loads(sent[-1].snapshot)
	since_last = revisions.diff(last, now, doc.currency or "")
	if since_last:
		return sent[-1].revision + 1, True, since_last
	if len(sent) == 1:
		return sent[-1].revision, False, []
	return sent[-1].revision, False, revisions.diff(json.loads(sent[-2].snapshot), now, doc.currency or "")


def record_revision(doc: Any) -> str:
	"""Keep the scope as sent. Refuses when nothing changed since the last one."""
	sent = recorded(doc)
	now = current_snapshot(doc)
	if sent and not revisions.diff(json.loads(sent[-1].snapshot), now, doc.currency or ""):
		frappe.throw(_("Nothing has changed since revision {0}.").format(sent[-1].revision))
	number = (sent[-1].revision if sent else 0) + 1
	revision = frappe.get_doc(
		{
			"doctype": "Scope of Work Revision",
			"scope": doc.name,
			"revision": number,
			"sent_on": now_datetime(),
			"snapshot": json.dumps(now, indent=1),
		}
	)
	revision.insert(ignore_permissions=True)
	doc.db_set("revision", number)
	revision.db_set("document", t.markdown(build(doc)))
	return revision.name


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
	revision, draft, changes = revision_state(doc)
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
		revision=revision,
		revision_draft=draft,
		revision_changes=changes,
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
	"""Write the document, the drawing and the PDF as attachments of the scope, replacing earlier copies."""
	from scope_of_work import printing

	tree = build(doc)
	files = {
		MD_NAME.format(name=doc.name): t.markdown(tree),
		SVG_NAME.format(name=doc.name): t.svg(tree),
		printing.PDF_NAME.format(name=doc.name): printing.pdf(doc),
	}
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


# ---- delivery and billing


def chosen_tasks(tree: t.Tree) -> dict[str, str]:
	"""Each charged item's ID, plus each choice group's ID mapped to its chosen option's ID."""
	out = {}
	for e, alternative in quote_rows(tree):
		if alternative:
			continue
		out[e.id] = e.id
		if e.choice_of:
			out[e.choice_of] = e.id
	return out


def make_project(doc: Any) -> str:
	"""A Project with one Task per item the client accepted, each depending on its prerequisites' Tasks, tagged
	with its stack component. Only for an Accepted scope; refuses if the scope already has a Project."""
	if doc.status != "Accepted":
		frappe.throw(_("Make the Project once the scope is Accepted."))
	if doc.project:
		frappe.throw(_("This scope already has Project {0}.").format(doc.project))
	tree = build(doc)
	charged = chosen_tasks(tree)
	if not charged:
		frappe.throw(_("Nothing is opted in, so there is nothing to deliver."))
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": f"{doc.title} ({doc.prepared_for or doc.party})"[:140],
			"company": doc.company,
			"customer": doc.party if doc.party_type == "Customer" else None,
			"expected_start_date": frappe.utils.today(),
		}
	).insert()
	from frappe.desk.doctype.tag.tag import add_tag

	tasks: dict[str, str] = {}
	for e in tree.ordered():
		if e.id not in charged.values() or e.id in tasks:
			continue
		group = tree.by_id[e.choice_of] if e.choice_of else e
		depends = []
		for parent in group.requires + group.any_of:
			if parent in charged and charged[parent] in tasks:
				depends.append({"task": tasks[charged[parent]]})
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": f"{e.id} {e.name}"[:140],
				"project": project.name,
				"description": describe(e),
				"depends_on": depends,
			}
		).insert()
		tasks[e.id] = task.name
		if e.stack:
			add_tag(e.stack, "Task", task.name)
	doc.db_set("project", project.name)
	return project.name


def make_subscription(doc: Any, start_date: str | None = None) -> str:
	"""One Subscription for the accepted per-month items, its invoices left as drafts. Only for an Accepted scope
	for a Customer, with every per-month item priced."""
	if doc.status != "Accepted":
		frappe.throw(_("Make the Subscription once the scope is Accepted."))
	if doc.party_type != "Customer":
		frappe.throw(_("A Subscription needs a Customer; this scope is for a {0}.").format(doc.party_type))
	if doc.subscription:
		frappe.throw(_("This scope already has Subscription {0}.").format(doc.subscription))
	tree = build(doc)
	by_id = {row.scope_id: row for row in doc.items}
	monthly = [e for e in tree.entries if tree.counted(e) and e.charge == t.PER_MONTH]
	if not monthly:
		frappe.throw(_("No accepted item is charged per month."))
	unpriced = [e.id for e in monthly if not e.rate]
	if unpriced:
		frappe.throw(_("Price {0} first.").format(", ".join(unpriced)))
	plans = []
	for e in monthly:
		code = by_id[e.id].item_code
		plan = frappe.db.get_value(
			"Subscription Plan",
			{
				"item": code,
				"price_determination": "Fixed Rate",
				"cost": float(e.rate),
				"currency": doc.currency,
				"billing_interval": "Month",
				"billing_interval_count": 1,
			},
		)
		if not plan:
			plan = (
				frappe.get_doc(
					{
						"doctype": "Subscription Plan",
						"plan_name": f"{code} {doc.currency} {float(e.rate):.2f} monthly"[:140],
						"item": code,
						"currency": doc.currency,
						"price_determination": "Fixed Rate",
						"cost": float(e.rate),
						"billing_interval": "Month",
						"billing_interval_count": 1,
					}
				)
				.insert()
				.name
			)
		plans.append({"plan": plan, "qty": 1})
	subscription = frappe.get_doc(
		{
			"doctype": "Subscription",
			"party_type": "Customer",
			"party": doc.party,
			"company": doc.company,
			"start_date": start_date or frappe.utils.today(),
			"plans": plans,
			"submit_invoice": 0,
			"generate_invoice_at": "Beginning of the current subscription period",
		}
	).insert()
	doc.db_set("subscription", subscription.name)
	return subscription.name


# ---- the client's page


def share_with_client(doc: Any) -> str:
	"""Give the scope a fresh client key (any earlier link stops working) and return the page's address."""
	key = frappe.generate_hash(length=32)
	link = frappe.utils.get_url(f"/scope?key={key}")
	doc.db_set({"client_key": key, "client_link": link})
	return link


def revoke_client_link(doc: Any) -> None:
	doc.db_set({"client_key": None, "client_link": None})


def apply_client_choice(doc: Any, ids: list[str]) -> list[str]:
	"""Set Opted in from the client's ticks. Only items the client may choose change (not required, later,
	delivered or withdrawn ones); the tree's own checks then refuse a choice that breaks a prerequisite.
	Returns the IDs now opted in."""
	chosen = set(ids)
	rows = [r for r in doc.items if not r.withdrawn]
	known = {r.scope_id for r in rows}
	unknown = sorted(chosen - known)
	if unknown:
		frappe.throw(_("Not on this scope: {0}").format(", ".join(unknown)))
	for row in rows:
		if row.is_choice_group or row.later or row.delivered or (row.required and not row.choice_of):
			continue
		row.opted_in = int(row.scope_id in chosen)
	doc.client_responded_on = now_datetime()
	doc.save(ignore_permissions=True)
	ticked = sorted(r.scope_id for r in rows if r.opted_in)
	doc.add_comment(
		"Comment", _("The client saved their choices on the scope page: {0}").format(", ".join(ticked) or "none")
	)
	return ticked
