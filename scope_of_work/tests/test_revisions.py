# SPDX-License-Identifier: AGPL-3.0-or-later
"""The change list between two sendings, without a bench: `python3 -m unittest scope_of_work.tests.test_revisions`."""

from __future__ import annotations

import unittest

from scope_of_work import revisions
from scope_of_work import tree as t


def row(scope_id: str, **values) -> dict:
	base = {
		"scope_id": scope_id,
		"item_name": f"Item {scope_id}",
		"stack": "ERPNext",
		"rate": 100,
		"charge": "One-time",
	}
	return revisions.snapshot_row({**base, **values})


class Diff(unittest.TestCase):
	def test_no_change(self):
		self.assertEqual(revisions.diff([row("W1")], [row("W1")]), [])

	def test_every_kind_of_change(self):
		old = [row("W1"), row("W2"), row("W3", opted_in=1), row("W4")]
		new = [
			row("W1", rate=150, delivers="A new point"),
			row("W2", withdrawn=1),
			row("W3", item_name="Renamed", stack="WordPress"),
			row("W5", later=1),
		]
		self.assertEqual(
			revisions.diff(old, new, "CAD"),
			[
				"W1 Item W1: price CAD 100.00 → CAD 150.00.",
				"W1 Item W1: delivers reworded.",
				"W2 Item W2: withdrawn; its ID is retired.",
				"W3: renamed from “Item W3” to “Renamed”.",
				"W3 Renamed: now built on WordPress (was ERPNext).",
				"W3 Renamed: no longer opted in.",
				"W5 Item W5: added (later item).",
				"W4 Item W4: removed.",
			],
		)

	def test_unpriced_reads_tbs(self):
		self.assertEqual(
			revisions.diff([row("F1", rate=0)], [row("F1", rate=50)], "CAD"), ["F1 Item F1: price TBS → CAD 50.00."]
		)


class Document(unittest.TestCase):
	def scope(self, **values) -> t.Scope:
		return t.Scope(
			title="T",
			prepared_for="C",
			date="2026-11-24",
			entries=[t.Entry("F1", "Root", "F", stack="ERPNext")],
			branches=[t.Branch("F", "Foundation", "#000")],
			**values,
		)

	def test_revision_header_and_changes(self):
		doc = t.markdown(t.Tree(self.scope(revision=2, revision_changes=["F1 Root: price TBS → CAD 50.00."])))
		self.assertIn("**Revision:** 2", doc)
		self.assertIn("## 1. Changes since revision 1\n\n- F1 Root: price TBS → CAD 50.00.", doc)

	def test_draft_revision(self):
		doc = t.markdown(t.Tree(self.scope(revision=3, revision_draft=True, revision_changes=["x"])))
		self.assertIn("**Revision:** 3 (draft, not yet sent)", doc)

	def test_first_sending_has_no_change_section(self):
		doc = t.markdown(t.Tree(self.scope(revision=1)))
		self.assertNotIn("Changes since", doc)


if __name__ == "__main__":
	unittest.main()
