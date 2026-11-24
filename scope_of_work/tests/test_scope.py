# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scopes on the real ERPNext test DB: the catalogue as Items, copying into a client's scope (prerequisites, IDs,
prices, client-provides), the IDs frozen once sent, opting in the highlights, and the draft Quotation and
Contract. ``ERPNextTestSuite`` is the base because importing it builds ERPNext's test records (company,
customer, UOM), which a fresh bench does not have."""

from __future__ import annotations

import json
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
ANALYTICS = "_Test SOW Analytics"
PACKAGE = "_Test SOW Web Starter"
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
			"scope_stack": None if values.get("scope_is_choice_group") else values.pop("stack", "ERPNext"),
			"scope_requires": [{"requirement": r} for r in requires],
			**values,
		}
	).insert(ignore_permissions=True)


class ScopeTestCase(ERPNextTestSuite):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		ensure_fields()
		for component in ("ERPNext", "Proxmox", "WordPress", "Matomo"):
			ensure("Scope Stack Component", component, {"component_name": component})
		for order, (letter, group) in enumerate(GROUPS.items()):
			ensure("Item Group", group, {"item_group_name": group, "parent_item_group": ROOT_GROUP})
			frappe.db.set_value(
				"Item Group",
				group,
				{"scope_branch_letter": letter, "scope_branch_colour": "#336699", "scope_branch_order": order},
			)
		ensure("Price List", PRICE_LIST, {"price_list_name": PRICE_LIST, "currency": "INR", "selling": 1, "enabled": 1})
		catalogue(HOSTING, GROUPS["H"], scope_is_choice_group=1, scope_required=1)
		catalogue(
			OWN, GROUPS["H"], stack="Proxmox", scope_choice_group=HOSTING, scope_provides="A place for the server."
		)
		catalogue(HOSTED, GROUPS["H"], stack="Proxmox", scope_choice_group=HOSTING, scope_charge="Per month")
		catalogue(
			FOUNDATION,
			GROUPS["F"],
			(HOSTING,),
			scope_required=1,
			scope_delivers="ERPNext installed\nDaily backups",
			scope_acceptance="A sale is recorded.",
		)
		catalogue(ANALYTICS, GROUPS["W"], (FOUNDATION,), stack="Matomo")
		catalogue(
			SITE,
			GROUPS["W"],
			(FOUNDATION,),
			stack="WordPress",
			scope_hours=12,
			scope_cost=3000,
			scope_suggests=[{"item": ANALYTICS, "reason": "See which pages bring customers in."}],
			scope_provides="The domain.",
		)
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
		self.assertEqual((rows[SITE].stack, rows[OWN].stack, rows[HOSTING].stack), ("WordPress", "Proxmox", ""))
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
		self.assertIn("<b>Built on:</b> WordPress", quotation.items[3].description)
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
		self.assertEqual(
			sorted(files), sorted([f"{doc.name} scope.md", f"{doc.name} scope.pdf", f"{doc.name} tree.svg"])
		)
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
				{
					"code": codes[5],
					"id": "X3",
					"stack": "ERPNext",
					"name": "Later",
					"branch": "W",
					"any_of": ["W7", "F1"],
					"later": True,
				},
				{"code": codes[0], "id": "H1", "name": "Hosting", "branch": "H", "is_choice": True, "required": True},
				{
					"code": codes[1],
					"id": "H1a",
					"stack": "Proxmox",
					"name": "Own",
					"branch": "H",
					"choice_of": "H1",
					"default_option": True,
				},
				{
					"code": codes[2],
					"id": "H1b",
					"stack": "Proxmox",
					"name": "Hosted",
					"branch": "H",
					"choice_of": "H1",
					"charge": "Per month",
				},
				{
					"code": codes[3],
					"id": "F1",
					"stack": "ERPNext",
					"name": "Root",
					"branch": "F",
					"requires": ["H1"],
					"required": True,
				},
				{
					"code": codes[4],
					"id": "W7",
					"stack": "Matomo",
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
		self.assertTrue(frappe.db.exists("Scope Stack Component", "Matomo"), "a new component is created")
		self.assertEqual(frappe.db.get_value("Item", codes[4], "scope_stack"), "Matomo")
		self.assertEqual([(p.items, p.provides) for p in doc.provides], [("W7", "The domain.")])
		later = frappe.get_doc("Item", codes[5])
		self.assertEqual([(r.requirement, r.any_of) for r in later.scope_requires], [(codes[4], 1), (codes[3], 1)])
		self.assertEqual(frappe.db.get_value("Item", codes[1], "scope_choice_group"), codes[0])
		scope.add_items(doc, [SITE])
		self.assertEqual(self.rows(doc)[SITE].scope_id, "W8", "new items take the next free number after imported IDs")


def accepted_scope(case: ScopeTestCase, monthly: bool = False) -> Any:
	"""Store requested, its tree opted in, hosting by the per-month option when asked, status Accepted."""
	doc = case.new_scope()
	scope.add_items(doc, [STORE], requested=True)
	case.rows(doc)[OWN].default_option = 1
	scope.opt_in_highlights(doc)
	if monthly:
		case.rows(doc)[OWN].opted_in = 0
		case.rows(doc)[HOSTED].opted_in = 1
	doc.status = "Accepted"
	doc.save()
	return doc


class Estimate(ScopeTestCase):
	def test_margin_totals_and_below_cost(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		self.rows(doc)[SITE].opted_in = 1
		doc.save()
		site = self.rows(doc)[SITE]
		self.assertEqual((site.hours, site.cost), (12, 3000))
		self.assertAlmostEqual(site.margin, -20.0)
		self.assertEqual(doc.total_price, 4000 + 6000 + 2500, "default option, required root and the opted-in site")
		self.assertEqual(doc.total_cost, 3000)
		self.assertEqual(doc.total_hours, 12)
		self.assertEqual(doc.below_cost, "W1")
		self.assertNotIn("3,000", scope.t.markdown(scope.build(doc)), "the internal cost is never printed")


class Packages(ScopeTestCase):
	def test_package_and_suggestions(self):
		if frappe.db.exists("Scope Package", PACKAGE):
			frappe.delete_doc("Scope Package", PACKAGE, force=True)
		frappe.get_doc(
			{
				"doctype": "Scope Package",
				"package_name": PACKAGE,
				"items": [{"item_code": SITE}, {"item_code": INTAKE, "recommended": 1}],
			}
		).insert()
		doc = self.new_scope()
		added = scope.add_package(doc, PACKAGE)
		self.assertEqual(added, ["H1", "H1a", "H1b", "F1", "W1", "I1"])
		self.assertTrue(self.rows(doc)[INTAKE].recommended)
		self.assertFalse(self.rows(doc)[SITE].recommended)
		self.rows(doc)[OWN].default_option = 1
		doc.save()
		found = scope.suggestions(doc)
		self.assertEqual(
			[(s["item_code"], s["because"], s["reasons"]) for s in found],
			[(ANALYTICS, ["W1"], ["See which pages bring customers in."])],
		)
		scope.add_items(doc, [ANALYTICS], recommended=True)
		self.assertEqual(scope.suggestions(doc), [])


class Revisions(ScopeTestCase):
	def test_sending_records_and_the_next_revision_lists_changes(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		doc.save()
		self.assertEqual(scope.recorded(doc), [])
		doc.status = "Sent"
		doc.save()
		doc.reload()
		self.assertEqual(doc.revision, 1)
		self.assertIn("**Revision:** 1\n", scope.t.markdown(scope.build(doc)))
		self.rows(doc)[SITE].rate = 2750
		doc.save()
		draft = scope.t.markdown(scope.build(doc))
		self.assertIn("**Revision:** 2 (draft, not yet sent)", draft)
		self.assertIn("W1 Brochure Site: price INR 2,500.00 → INR 2,750.00.", draft)
		scope.record_revision(doc)
		doc.reload()
		sent = scope.t.markdown(scope.build(doc))
		self.assertIn("**Revision:** 2\n", sent)
		self.assertIn("## 1. Changes since revision 1", sent)
		stored = frappe.get_doc("Scope of Work Revision", f"{doc.name}-R2")
		self.assertIn("Changes since revision 1", stored.document)
		with self.assertRaises(frappe.ValidationError):
			scope.record_revision(doc)


class Printing(ScopeTestCase):
	def test_print_format_and_pdf(self):
		from scope_of_work import printing

		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		doc.save()
		html = frappe.get_print("Scope of Work", doc.name, "Scope of Work")
		self.assertIn("<svg", html)
		self.assertIn("How this scope works", html)
		self.assertTrue(printing.pdf(doc).startswith(b"%PDF"))
		urls = scope.attach_files(doc)
		self.assertIn(f"{doc.name} scope.pdf", urls)


class Delivery(ScopeTestCase):
	def test_project_tasks_follow_the_tree(self):
		doc = accepted_scope(self)
		name = scope.make_project(doc)
		tasks = {
			t.subject.split()[0]: t
			for t in frappe.get_all("Task", filters={"project": name}, fields=["name", "subject", "_user_tags"])
		}
		self.assertEqual(sorted(tasks), ["F1", "H1a", "I1", "W1", "W2"])
		store = frappe.get_doc("Task", tasks["W2"].name)
		self.assertEqual(sorted(d.task for d in store.depends_on), sorted([tasks["W1"].name, tasks["I1"].name]))
		root = frappe.get_doc("Task", tasks["F1"].name)
		self.assertEqual([d.task for d in root.depends_on], [tasks["H1a"].name], "the group maps to its chosen option")
		self.assertIn("WordPress", tasks["W1"]._user_tags or "")
		with self.assertRaises(frappe.ValidationError):
			scope.make_project(doc)

	def test_project_waits_for_acceptance(self):
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		doc.save()
		with self.assertRaises(frappe.ValidationError):
			scope.make_project(doc)

	def test_subscription_for_the_monthly_items(self):
		doc = accepted_scope(self, monthly=True)
		name = scope.make_subscription(doc, "2026-12-01")
		subscription = frappe.get_doc("Subscription", name)
		self.assertEqual((subscription.party, subscription.submit_invoice), (CUSTOMER, 0))
		plans = [frappe.get_doc("Subscription Plan", p.plan) for p in subscription.plans]
		self.assertEqual([(p.item, p.cost, p.billing_interval) for p in plans], [(HOSTED, 150, "Month")])
		with self.assertRaises(frappe.ValidationError):
			scope.make_subscription(doc)

	def test_no_subscription_without_monthly_items(self):
		doc = accepted_scope(self)
		with self.assertRaises(frappe.ValidationError):
			scope.make_subscription(doc)


class ClientPage(ScopeTestCase):
	def test_page_and_ticks(self):
		from scope_of_work import api
		from scope_of_work.www import scope as page

		doc = self.new_scope()
		scope.add_items(doc, [STORE], requested=True)
		self.rows(doc)[OWN].default_option = 1
		doc.save()
		link = scope.share_with_client(doc)
		doc.reload()
		self.assertTrue(link.endswith(f"/scope?key={doc.client_key}"))
		frappe.form_dict.key = doc.client_key
		context = page.get_context(frappe._dict())
		self.assertEqual(context.title, "Retail Platform")
		self.assertEqual([i["id"] for i in context["items"]][:4], ["H1", "H1a", "H1b", "F1"])
		self.assertTrue(next(i for i in context["items"] if i["id"] == "W2")["requested"])
		branches = [i["branch"] for i in context["items"]]
		runs = [b for n, b in enumerate(branches) if n == 0 or branches[n - 1] != b]
		self.assertEqual(len(runs), len(set(runs)), "each branch is one block on the client page")
		self.assertEqual(next(i for i in context["items"] if i["id"] == "W2")["meta"], "needs W1, I1")
		opt_in = api.client_opt_in.__wrapped__
		with self.assertRaises(frappe.ValidationError):
			opt_in(doc.client_key, json.dumps(["W2"]))  # W2 without W1 and I1
		ticked = opt_in(doc.client_key, json.dumps(["H1b", "W1", "I1", "W2"]))
		self.assertEqual(ticked, ["H1b", "I1", "W1", "W2"])
		doc.reload()
		self.assertTrue(doc.client_responded_on)
		self.assertFalse(self.rows(doc)[OWN].opted_in)
		with self.assertRaises(frappe.ValidationError):
			opt_in(doc.client_key, json.dumps(["Z9"]))
		scope.revoke_client_link(doc)
		frappe.form_dict.key = link.split("key=")[1]
		self.assertTrue(page.get_context(frappe._dict()).missing)
		with self.assertRaises(frappe.PermissionError):
			opt_in(link.split("key=")[1], "[]")

	def test_accepted_scope_is_locked(self):
		from scope_of_work import api

		doc = accepted_scope(self)
		scope.share_with_client(doc)
		doc.reload()
		with self.assertRaises(frappe.ValidationError):
			api.client_opt_in.__wrapped__(doc.client_key, "[]")


class FakeResponse:
	def __init__(self, status: int, content: bytes = b"", data: Any = None):
		self.status_code, self.content, self._data = status, content, data

	def json(self) -> Any:
		return {"ocs": {"data": self._data}}


class FakeNextcloud:
	"""Records every call and answers as Nextcloud does: MKCOL 201/405, PUT 201, PROPFIND 207 with the size,
	OCS shares listing and creating."""

	def __init__(self):
		self.calls, self.files, self.folders, self.shares, self.auth = [], {}, set(), [], None

	def request(self, method: str, url: str, timeout: int, **kwargs) -> FakeResponse:
		self.calls.append((method, url))
		if "/remote.php/dav/files/" in url:
			path = url.split("/remote.php/dav/files/", 1)[1].split("/", 1)[1]
			if method == "MKCOL":
				status = 405 if path in self.folders else 201
				self.folders.add(path)
				return FakeResponse(status)
			if method == "PUT":
				self.files[path] = kwargs["data"]
				return FakeResponse(201)
			if method == "PROPFIND":
				size = len(self.files[path])
				body = f'<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:getcontentlength>{size}</d:getcontentlength></d:prop></d:propstat></d:response></d:multistatus>'
				return FakeResponse(207, body.encode())
		if method == "GET":
			path = kwargs["params"]["path"]
			return FakeResponse(200, data=[s for s in self.shares if s["path"] == path])
		if method == "POST":
			data = kwargs["data"]
			self.shares.append({"path": data["path"], "share_type": data["shareType"], "share_with": data["shareWith"]})
			return FakeResponse(200, data={})
		return FakeResponse(500)


class Filing(ScopeTestCase):
	def test_files_go_to_nextcloud_and_attach_once(self):
		from urllib.parse import unquote

		from scope_of_work import filing

		frappe.db.set_single_value("Scope of Work Settings", "nextcloud_base_folder", "Scopes of Work")
		doc = self.new_scope()
		scope.add_items(doc, [SITE])
		self.rows(doc)[OWN].default_option = 1
		doc.deck_card = "https://cloud.example.com/apps/deck/board/12/card/397"
		doc.save()
		fake = FakeNextcloud()
		client = filing.Nextcloud("https://cloud.example.com", "agent", "secret", fake)
		result = filing.file_scope(doc, client)
		folder = f"Scopes of Work/{doc.prepared_for}"
		self.assertEqual(result["folder"], folder)
		self.assertEqual(result["card"], 397)
		stored = {unquote(p) for p in fake.files}
		self.assertEqual(
			stored, {f"{folder}/{doc.name} scope.md", f"{folder}/{doc.name} tree.svg", f"{folder}/{doc.name} scope.pdf"}
		)
		self.assertEqual(len(fake.shares), 3)
		again = filing.file_scope(doc, client)
		self.assertEqual(again["attached"], [], "an existing Deck attachment is not duplicated")
		self.assertEqual(len(fake.shares), 3)
		self.assertEqual(filing.card_id("397"), 397)
		with self.assertRaises(frappe.ValidationError):
			filing.card_id("board twelve")
