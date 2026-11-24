# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tree's rules, layout and outputs, without a bench: `python3 -m unittest scope_of_work.tests.test_tree`."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from scope_of_work import tree as t

BRANCHES = [
	t.Branch("H", "Hosting", "#3a9aa8"),
	t.Branch("F", "Foundation", "#5b6b7a"),
	t.Branch("W", "Web", "#2f6fb3"),
	t.Branch("I", "Inventory", "#2f8f5b"),
]


def entries() -> list[t.Entry]:
	"""A small tree with everything the form has: a required choice group, a root, a cross-branch item, a
	one-of-alternatives item and a later item."""
	return [
		t.Entry("H1", "Hosting", "H", is_choice=True, required=True),
		t.Entry("H1a", "Own server", "H", choice_of="H1", default_option=True, rate=Decimal("4000")),
		t.Entry("H1b", "Hosted", "H", choice_of="H1", charge=t.PER_MONTH, rate=Decimal("150")),
		t.Entry("F1", "Foundation", "F", requires=["H1"], required=True, rate=Decimal("6000"), delivers=["One", "Two"]),
		t.Entry("W1", "Brochure site", "W", requires=["F1"], rate=Decimal("2500")),
		t.Entry("I1", "Intake", "I", requires=["F1"]),
		t.Entry("W2", "Store", "W", requires=["W1", "I1"], acceptance="A test order is paid."),
		t.Entry("W3", "Gift cards", "W", any_of=["W2", "I1"]),
		t.Entry("X1", "Point of sale", "I", requires=["I1"], later=True),
	]


def scope(items: list[t.Entry] | None = None, **values) -> t.Scope:
	return t.Scope(
		title="Retail Platform",
		prepared_for="Test Client",
		date="2026-11-24",
		entries=entries() if items is None else items,
		branches=BRANCHES,
		**values,
	)


def find(items: list[t.Entry], eid: str) -> t.Entry:
	return next(e for e in items if e.id == eid)


class Rules(unittest.TestCase):
	def assertBroken(self, items: list[t.Entry], fragment: str) -> None:
		with self.assertRaises(t.TreeError) as caught:
			t.Tree(scope(items))
		self.assertTrue(any(fragment in p for p in caught.exception.problems), caught.exception.problems)

	def test_a_good_tree_builds(self):
		tree = t.Tree(scope())
		self.assertEqual(tree.tier["H1"], 0)
		self.assertEqual(tree.tier["H1b"], 0)
		self.assertEqual(tree.tier["F1"], 1)
		self.assertEqual(tree.tier["W2"], 3)
		self.assertEqual(tree.tier["W3"], 4)

	def test_unknown_prerequisite(self):
		items = entries()
		find(items, "W1").requires = ["F9"]
		self.assertBroken(items, "requires F9, which is not on the tree")

	def test_duplicate_id(self):
		items = entries() + [t.Entry("W1", "Again", "W", requires=["F1"])]
		self.assertBroken(items, "W1 is used twice")

	def test_bad_id(self):
		items = entries() + [t.Entry("web1", "Lower", "W", requires=["F1"])]
		self.assertBroken(items, "not an item ID")

	def test_cycle(self):
		items = entries()
		find(items, "W1").requires = ["W2"]
		self.assertBroken(items, "go round in a circle")

	def test_choice_group_needs_two_options(self):
		items = [e for e in entries() if e.id != "H1b"]
		self.assertBroken(items, "needs at least two options")

	def test_required_group_without_a_default_is_an_open_point(self):
		items = entries()
		find(items, "H1a").default_option = False
		tree = t.Tree(scope(items))
		self.assertEqual(t.undecided_groups(tree), ["H1"])
		self.assertIn("Which H1 option the quote is built on (its default).", t.markdown(tree))

	def test_require_the_group_not_an_option(self):
		items = entries()
		find(items, "F1").requires = ["H1a"]
		self.assertBroken(items, "require the choice group H1 instead")

	def test_priced_item_cannot_need_a_later_one(self):
		items = entries()
		find(items, "W3").any_of = ["X1"]
		self.assertBroken(items, "a later item")

	def test_opt_in_needs_prerequisites(self):
		items = entries()
		find(items, "W2").opted_in = True
		find(items, "W1").opted_in = True
		self.assertBroken(items, "W2 is opted in but needs I1")
		find(items, "I1").delivered = True
		t.Tree(scope(items))

	def test_any_of_satisfied_by_one(self):
		items = entries()
		find(items, "W3").opted_in = True
		self.assertBroken(items, "needs W2 or I1")
		find(items, "I1").opted_in = True
		t.Tree(scope(items))

	def test_withdrawn_rows_leave_the_tree_but_keep_their_id(self):
		items = entries()
		find(items, "W3").withdrawn = True
		tree = t.Tree(scope(items))
		self.assertNotIn("W3", tree.by_id)
		self.assertEqual(t.next_id({e.id for e in items}, "W"), "W4")


class Ids(unittest.TestCase):
	def test_next_id(self):
		self.assertEqual(t.next_id(set(), "F"), "F1")
		self.assertEqual(t.next_id({"F1", "F2", "W7", "F1a"}, "F"), "F3")
		self.assertEqual(t.next_id({"H1", "H1a"}, "", option_of="H1"), "H1b")


class Layout(unittest.TestCase):
	def test_no_two_boxes_share_a_place(self):
		tree = t.Tree(scope())
		boxes = [(tree.tier[e.id], tree.row[e.id], tree.height(e)) for e in tree.entries if not e.choice_of]
		for i, (tier, top, height) in enumerate(boxes):
			for other_tier, other_top, other_height in boxes[i + 1 :]:
				if tier == other_tier:
					self.assertTrue(top + height <= other_top + 1e-9 or other_top + other_height <= top + 1e-9)

	def test_options_sit_inside_their_group(self):
		tree = t.Tree(scope())
		self.assertGreater(tree.row["H1a"], tree.row["H1"])
		self.assertLess(tree.row["H1b"] + 1, tree.row["H1"] + tree.height(tree.by_id["H1"]) + 1e-9)

	def test_manual_rows_that_collide_are_refused(self):
		items = entries()
		find(items, "W1").row = 3
		find(items, "I1").row = 3.5
		with self.assertRaises(t.TreeError):
			t.Tree(scope(items))


class Svg(unittest.TestCase):
	def test_valid_and_highlighted(self):
		items = entries()
		find(items, "W2").requested = True
		find(items, "I1").recommended = True
		drawing = t.svg(t.Tree(scope(items)))
		ET.fromstring(drawing)
		self.assertIn("REQUESTED", drawing)
		self.assertIn("RECOMMENDED", drawing)
		self.assertIn("Requested by you", drawing)
		self.assertIn("stroke-dasharray", drawing)

	def test_no_legend_for_highlights_when_there_are_none(self):
		self.assertNotIn("Requested by you", t.svg(t.Tree(scope())))

	def test_long_names_fit(self):
		text, size = t.fit("W9  " + "A very long item name that cannot possibly fit in one box", 230)
		self.assertTrue(text.endswith("…"))
		self.assertGreaterEqual(size, 11)


class Markdown(unittest.TestCase):
	def test_sections_in_order(self):
		doc = t.markdown(
			t.Tree(scope(provides=[("W1", "The domain")], exclusions=["Hardware"], assumptions=["Remote work"]))
		)
		headings = [line for line in doc.splitlines() if line.startswith("## ")]
		self.assertEqual(
			headings,
			[
				"## 1. How this scope works",
				"## 2. The tree",
				"## 3. Every item",
				"## 4. What each item delivers",
				"## 5. Later items (on the tree, not priced here)",
				"## 6. What the client provides",
				"## 7. Not included in any item",
				"## 8. Assumptions",
				"## 9. Price",
				"## 10. Changes and warranty",
				"## 11. Open Points",
				"## 12. Acceptance of this scope",
			],
		)

	def test_empty_optional_sections_are_left_out(self):
		doc = t.markdown(t.Tree(scope()))
		for title in ("What the client provides", "Not included in any item", "Assumptions"):
			self.assertNotIn(title, doc)

	def test_highlights_section_and_missing_prerequisites(self):
		items = entries()
		w2 = find(items, "W2")
		w2.requested, w2.reason = True, "Asked at the first meeting."
		find(items, "I1").recommended = True
		doc = t.markdown(t.Tree(scope(items)))
		self.assertIn("## 2. Your requests and our recommendations", doc)
		self.assertIn("| W2 | Store | ✔ |  | Asked at the first meeting. |", doc)
		self.assertIn("Your requests also need: I1 Intake, W1 Brochure site.", doc)
		self.assertIn("W2 Store  [requested]", doc)

	def test_price_table_choice_group_and_tbs(self):
		doc = t.markdown(t.Tree(scope()))
		self.assertIn("| H1 | Hosting: choose one | none | | | Required |", doc)
		self.assertIn("| H1a | ↳ Own server *(default)* |  | CAD 4,000.00 | one-time | ◯ |", doc)
		self.assertIn("| H1b | ↳ Hosted |  | CAD 150.00 | per month | ◯ |", doc)
		self.assertIn("| I1 | Intake | F1 | TBS | one-time | ☐ |", doc)
		self.assertNotIn("| X1 | Point of sale | I1 | TBS", doc)
		self.assertIn("1. Price of I1, W2, W3.", doc)

	def test_totals_use_the_default_option(self):
		items = entries()
		find(items, "W1").opted_in = True
		doc = t.markdown(t.Tree(scope(items)))
		self.assertIn("Total of the items marked: CAD 12,500.00 one-time.", doc)
		find(items, "H1b").opted_in = True
		doc = t.markdown(t.Tree(scope(items)))
		self.assertIn("CAD 8,500.00 one-time, CAD 150.00 per month", doc)

	def test_no_total_while_a_marked_item_is_unpriced(self):
		items = entries()
		find(items, "I1").opted_in = True
		self.assertNotIn("Total of the items marked", t.markdown(t.Tree(scope(items))))

	def test_text_tree(self):
		doc = t.markdown(t.Tree(scope()))
		self.assertIn("H1 Hosting  (required: choose one)", doc)
		self.assertIn("◯ H1a Own server", doc)
		self.assertIn("W2 Store   (also needs I1)", doc)
		self.assertIn("X1 Point of sale  [later]", doc)


if __name__ == "__main__":
	unittest.main()
