# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scopes on the real ERPNext test DB: the catalogue as Items, copying into a client's scope (prerequisites, IDs,
prices, client-provides), the IDs frozen once sent, opting in the highlights, and the draft Quotation and
Contract. ``ERPNextTestSuite`` is the base because importing it builds ERPNext's test records (company,
customer, UOM), which a fresh bench does not have."""

from __future__ import annotations

from typing import Any

import frappe
from erpnext.tests.utils import ERPNextTestSuite

from scope_of_work import scope
from scope_of_work.install import ensure_fields

COMPANY = "_Test Company"
CUSTOMER = "_Test Customer"
PRICE_LIST = "_Test SOW Price List"
ROOT_GROUP = "All Item Groups"
GROUPS = {"H": "_Test SOW Hosting", "F": "_Test SOW Foundation", "W": "_Test SOW Web", "I": "_Test SOW Inventory"}

HOSTING = "_Test SOW Hosting Choice"
OWN = "_Test SOW Own Server"
HOSTED = "_Test SOW Hosted"
FOUNDATION = "_Test SOW Foundation Item"
SITE = "_Test SOW Brochure Site"
INTAKE = "_Test SOW Intake"
STORE = "_Test SOW Store"
LATER = "_Test SOW Point of Sale"
OUTSIDER = "_Test SOW Not Catalogued"

PRICES = {OWN: 4000, HOSTED: 150, FOUNDATION: 6000, SITE: 2500, STORE: 5000}


def ensure(doctype: str, name: str, values: dict[str, Any]) -> None:
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def catalogue(code: str, group: str, requires: tuple[str, ...] = (), **values: Any) -> None:
	if frappe.db.exists("Item", code):
		frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code.removeprefix("_Test SOW "),
			"item_group": group,
			"stock_uom": "_Test UOM",
			"is_stock_item": 0,
			"is_sales_item": 1,
			"scope_enabled": 1,
			"scope_requires": [{"requirement": r} for r in requires],
			**values,
		}
	).insert(ignore_permissions=True)


class ScopeTestCase(ERPNextTestSuite):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		ensure_fields()
		for order, (letter, group) in enumerate(GROUPS.items()):
			ensure("Item Group", group, {"item_group_name": group, "parent_item_group": ROOT_GROUP})
			frappe.db.set_value(
				"Item Group",
				group,
				{"scope_branch_letter": letter, "scope_branch_colour": "#336699", "scope_branch_order": order},
			)
		ensure("Price List", PRICE_LIST, {"price_list_name": PRICE_LIST, "currency": "INR", "selling": 1, "enabled": 1})
		catalogue(HOSTING, GROUPS["H"], scope_is_choice_group=1, scope_required=1)
		catalogue(OWN, GROUPS["H"], scope_choice_group=HOSTING, scope_provides="A place for the server.")
		catalogue(HOSTED, GROUPS["H"], scope_choice_group=HOSTING, scope_charge="Per month")
		catalogue(
			FOUNDATION,
			GROUPS["F"],
			(HOSTING,),
			scope_required=1,
			scope_delivers="ERPNext installed\nDaily backups",
			scope_acceptance="A sale is recorded.",
		)
		catalogue(SITE, GROUPS["W"], (FOUNDATION,), scope_provides="The domain.")
		catalogue(INTAKE, GROUPS["I"], (FOUNDATION,))
		catalogue(STORE, GROUPS["W"], (SITE, INTAKE), scope_acceptance="A test order is paid.")
		catalogue(LATER, GROUPS["I"], (INTAKE,), scope_later=1)
		if frappe.db.exists("Item", OUTSIDER):
			frappe.delete_doc("Item", OUTSIDER, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": OUTSIDER,
				"item_group": GROUPS["W"],
				"stock_uom": "_Test UOM",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.delete("Item Price", {"price_list": PRICE_LIST})
		for code, rate in PRICES.items():
			frappe.get_doc(
				{"doctype": "Item Price", "price_list": PRICE_LIST, "item_code": code, "price_list_rate": rate}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	def new_scope(self, party_type: str = "Customer", party: str = CUSTOMER) -> Any:
		return frappe.get_doc(
			{
				"doctype": "Scope of Work",
				"title": "Retail Platform",
				"party_type": party_type,
				"party": party,
				"company": COMPANY,
				"price_list": PRICE_LIST,
			}
		).insert()

	def rows(self, doc: Any) -> dict[str, Any]:
		return {row.item_code: row for row in doc.items}


class Catalogue(ScopeTestCase):
	def test_store_pulls_in_its_whole_tree(self):
		doc = self.new_scope()
		added = scope.add_items(doc, [STORE], requested=True)
		doc.save()
		rows = self.rows(doc)
		self.assertEqual(added, ["H1", "H1a", "H1b", "F1", "W1", "I1", "W2"])
		self.assertEqual(rows[OWN].choice_of, "H1")
		self.assertEqual(rows[FOUNDATION].requires, "H1")
		self.assertEqual(rows[STORE].requires, "W1, I1")
		self.assertTrue(rows[STORE].requested)
		self.assertFalse(rows[SITE].requested, "only the item named is a request; prerequisites are not")
		self.assertEqual(rows[FOUNDATION].delivers, "ERPNext installed\nDaily backups")
		self.assertEqual(rows[HOSTED].charge, "Per month")
		self.assertEqual(rows[SITE].rate, 2500)
		self.assertEqual(rows[INTAKE].rate, 0, "no Item Price: stays zero, printed TBS")
		self.assertEqual(
			{(p.items, p.provides) for p in doc.provides}, {("H1a", "A place for the server."), ("W1", "The domain.")}
		)

	def test_numbering_continues_and_later_items_take_x(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		scope.add_items(doc, [LATER], recommended=True)
		doc.save()
		rows = self.rows(doc)
		self.assertEqual(rows[INTAKE].scope_id, "I1")
		self.assertEqual(rows[LATER].scope_id, "X1")
		self.assertTrue(rows[LATER].recommended)

	def test_an_item_outside_the_catalogue_is_refused(self):
		doc = self.new_scope()
		with self.assertRaises(frappe.ValidationError):
			scope.add_items(doc, [OUTSIDER])

	def test_broken_tree_is_refused_on_save(self):
		doc = self.new_scope()
		scope.add_items(doc, [STORE])
		self.rows(doc)[OWN].default_option = 1
		self.rows(doc)[STORE].opted_in = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_drafts_wait_for_the_default_option(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		doc.save()
		with self.assertRaises(frappe.ValidationError):
			scope.make_drafts(doc)


class Highlights(ScopeTestCase):
	def test_opt_in_takes_prerequisites_and_the_default_option(self):
		doc = self.new_scope()
		scope.add_items(doc, [STORE], requested=True)
		self.rows(doc)[OWN].default_option = 1
		ticked = scope.opt_in_highlights(doc)
		doc.save()
		self.assertEqual(sorted(ticked), sorted(["W2", "W1", "F1", "H1a", "I1"]))
		self.assertFalse(self.rows(doc)[HOSTED].opted_in)


class SentScope(ScopeTestCase):
	def test_ids_are_fixed_once_sent(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		doc.status = "Sent"
		doc.save()
		self.rows(doc)[SITE].scope_id = "W9"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		self.rows(doc)[SITE].withdrawn = 1
		doc.save()
		scope.add_items(doc, [INTAKE])
		self.assertEqual(self.rows(doc)[INTAKE].scope_id, "I1")
		doc.save()


class Drafts(ScopeTestCase):
	def opted_scope(self, **kwargs: Any) -> Any:
		doc = self.new_scope(**kwargs)
		scope.add_items(doc, [STORE], requested=True)
		self.rows(doc)[OWN].default_option = 1
		scope.opt_in_highlights(doc)
		doc.save()
		return doc

	def test_quotation_and_contract_for_a_customer(self):
		doc = self.opted_scope()
		made = scope.make_drafts(doc)
		quotation = frappe.get_doc("Quotation", made["quotation"])
		self.assertEqual(quotation.docstatus, 0)
		lines = [(row.item_name, row.is_alternative) for row in quotation.items]
		self.assertEqual(
			lines,
			[
				("H1a Own Server", 0),
				("H1b Hosted", 1),
				("F1 Foundation Item", 0),
				("W1 Brochure Site", 0),
				("I1 Intake", 0),
				("W2 Store", 0),
			],
		)
		# has_alternative_item is set by ERPNext on submit only; a draft keeps the alternatives by position.
		self.assertEqual(quotation.net_total, 4000 + 6000 + 2500 + 0 + 5000, "the alternative is left out of the total")
		self.assertIn("Acceptance:", quotation.items[2].description)
		contract = frappe.get_doc("Contract", made["contract"])
		self.assertEqual(contract.docstatus, 0)
		self.assertEqual((contract.document_type, contract.document_name), ("Quotation", quotation.name))
		self.assertEqual(
			[row.requirement for row in contract.fulfilment_terms],
			["H1a Own Server", "F1 Foundation Item", "W1 Brochure Site", "I1 Intake", "W2 Store"],
		)
		doc.reload()
		self.assertEqual((doc.quotation, doc.contract), (quotation.name, contract.name))
		files = frappe.get_all(
			"File", filters={"attached_to_doctype": "Scope of Work", "attached_to_name": doc.name}, pluck="file_name"
		)
		self.assertEqual(sorted(files), sorted([f"{doc.name} scope.md", f"{doc.name} tree.svg"]))
		with self.assertRaises(frappe.ValidationError):
			scope.make_drafts(doc)

	def test_a_lead_gets_a_quotation_only(self):
		lead = frappe.get_doc(
			{"doctype": "Lead", "lead_name": "SOW Test Lead", "company_name": "SOW Test Shop"}
		).insert(ignore_permissions=True)
		doc = self.opted_scope(party_type="Lead", party=lead.name)
		self.assertEqual(doc.prepared_for, "SOW Test Shop")
		made = scope.make_drafts(doc)
		self.assertIsNone(made["contract"])
		self.assertEqual(frappe.db.get_value("Quotation", made["quotation"], "quotation_to"), "Lead")


class Import(ScopeTestCase):
	def test_a_scope_file_keeps_its_ids_and_builds_the_catalogue(self):
		from scope_of_work import importer

		codes = [
			"_Test SOW Imp Group",
			"_Test SOW Imp A",
			"_Test SOW Imp B",
			"_Test SOW Imp Root",
			"_Test SOW Imp Site",
		]
		codes += ["_Test SOW Imp Later"]
		for code in codes:
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		data = {
			"uom": "_Test UOM",
			"branches": [
				{"letter": "H", "name": "Hosting", "item_group": GROUPS["H"], "order": 0},
				{"letter": "F", "name": "Foundation", "item_group": GROUPS["F"], "order": 1},
				{"letter": "W", "name": "Web", "item_group": GROUPS["W"], "order": 2},
			],
			"items": [
				{"code": codes[5], "id": "X3", "name": "Later", "branch": "W", "any_of": ["W7", "F1"], "later": True},
				{"code": codes[0], "id": "H1", "name": "Hosting", "branch": "H", "is_choice": True, "required": True},
				{
					"code": codes[1],
					"id": "H1a",
					"name": "Own",
					"branch": "H",
					"choice_of": "H1",
					"default_option": True,
				},
				{
					"code": codes[2],
					"id": "H1b",
					"name": "Hosted",
					"branch": "H",
					"choice_of": "H1",
					"charge": "Per month",
				},
				{"code": codes[3], "id": "F1", "name": "Root", "branch": "F", "requires": ["H1"], "required": True},
				{
					"code": codes[4],
					"id": "W7",
					"name": "Site",
					"branch": "W",
					"requires": ["F1"],
					"delivers": ["A page", "A form"],
					"provides": "The domain.",
					"requested": True,
					"reason": "Asked for it.",
				},
			],
			"scope": {"title": "Imported", "party": CUSTOMER, "company": COMPANY, "price_list": PRICE_LIST},
		}
		name = importer.import_scope(data)
		self.assertEqual(scope.branch_of(GROUPS["W"]).name, "Web", "the branch label, not the Item Group's name")
		doc = frappe.get_doc("Scope of Work", name)
		self.assertEqual([r.scope_id for r in doc.items], ["X3", "H1", "H1a", "H1b", "F1", "W7"])
		self.assertEqual(self.rows(doc)[codes[4]].delivers, "A page\nA form")
		self.assertEqual([(p.items, p.provides) for p in doc.provides], [("W7", "The domain.")])
		later = frappe.get_doc("Item", codes[5])
		self.assertEqual([(r.requirement, r.any_of) for r in later.scope_requires], [(codes[4], 1), (codes[3], 1)])
		self.assertEqual(frappe.db.get_value("Item", codes[1], "scope_choice_group"), codes[0])
		scope.add_items(doc, [SITE])
		self.assertEqual(self.rows(doc)[SITE].scope_id, "W8", "new items take the next free number after imported IDs")
