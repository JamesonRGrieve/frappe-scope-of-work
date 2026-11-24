# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from scope_of_work import scope

DEFAULTS = ("signatory", "tax_note", "provides_general", "exclusions", "assumptions", "changes")


class ScopeofWork(Document):
	def before_insert(self) -> None:
		settings = frappe.get_cached_doc("Scope of Work Settings")
		for field in DEFAULTS:
			if not self.get(field) and settings.get(field):
				self.set(field, settings.get(field))

	def validate(self) -> None:
		if not self.prepared_for:
			self.prepared_for = scope.party_display(self)
		for row in self.items:
			if not row.branch:
				row.branch = frappe.get_cached_value("Item", row.item_code, "item_group")
			if not row.item_name:
				row.item_name = frappe.get_cached_value("Item", row.item_code, "item_name")
		self.keep_sent_ids()
		scope.estimate(self, scope.build(self))

	def on_update(self) -> None:
		"""Sending the scope records a revision, unless nothing changed since the last one."""
		before = self.get_doc_before_save()
		if self.status != "Sent" or (before and before.status == "Sent"):
			return
		revision, draft, _changes = scope.revision_state(self)
		if revision == 0 or draft:
			scope.record_revision(self)

	def keep_sent_ids(self) -> None:
		"""Once a scope has gone to the client its IDs are the join to the quote, contract and invoices."""
		before = self.get_doc_before_save()
		if not before or before.status not in scope.FROZEN:
			return
		now = {row.scope_id: row.item_code for row in self.items}
		for row in before.items:
			if now.get(row.scope_id) != row.item_code:
				frappe.throw(
					_(
						"{0} ({1}) went to the client with this ID. Tick Withdrawn instead of removing or renumbering it."
					).format(row.scope_id, row.item_code)
				)
