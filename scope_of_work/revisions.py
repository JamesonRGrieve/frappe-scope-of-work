# SPDX-License-Identifier: AGPL-3.0-or-later
"""What changed between two sendings of a scope, in words the client can read. Pure: snapshots are plain dicts."""

from __future__ import annotations

from typing import Any

FIELDS = ("name", "stack", "rate", "charge", "requires", "any_of", "delivers", "acceptance", "note", "withdrawn")


def snapshot_row(row: Any) -> dict[str, Any]:
	"""The parts of a scope row the client sees, in a form that compares cleanly."""
	get = row.get if isinstance(row, dict) else lambda key, default=None: getattr(row, key, default)
	return {
		"id": get("scope_id"),
		"name": get("item_name") or "",
		"stack": get("stack") or "",
		"rate": float(get("rate") or 0),
		"charge": get("charge") or "",
		"requires": get("requires") or "",
		"any_of": get("any_of") or "",
		"delivers": (get("delivers") or "").strip(),
		"acceptance": (get("acceptance") or "").strip(),
		"note": (get("note") or "").strip(),
		"later": bool(get("later")),
		"opted_in": bool(get("opted_in")),
		"withdrawn": bool(get("withdrawn")),
		"is_choice_group": bool(get("is_choice_group")),
	}


def money(value: float, currency: str) -> str:
	return f"{currency} {value:,.2f}" if value else "TBS"


def diff(old: list[dict[str, Any]], new: list[dict[str, Any]], currency: str = "") -> list[str]:
	"""One line per change, in item order: added, withdrawn, renamed, repriced, reworded, re-based, opted in or out."""
	before = {row["id"]: row for row in old}
	lines = []
	for row in new:
		label = f"{row['id']} {row['name']}"
		was = before.get(row["id"])
		if was is None:
			if not row["withdrawn"]:
				lines.append(f"{label}: added" + (" (later item)" if row["later"] else "") + ".")
			continue
		if row["withdrawn"] and not was["withdrawn"]:
			lines.append(f"{label}: withdrawn; its ID is retired.")
			continue
		if row["withdrawn"]:
			continue
		if row["name"] != was["name"]:
			lines.append(f"{row['id']}: renamed from “{was['name']}” to “{row['name']}”.")
		if not row["is_choice_group"] and not row["later"]:
			if row["rate"] != was["rate"]:
				lines.append(f"{label}: price {money(was['rate'], currency)} → {money(row['rate'], currency)}.")
			if row["charge"] != was["charge"]:
				lines.append(f"{label}: now charged {row['charge'].lower()} (was {was['charge'].lower()}).")
		if row["stack"] != was["stack"]:
			lines.append(
				f"{label}: now built on {row['stack'] or 'nothing named'} (was {was['stack'] or 'not named'})."
			)
		if (row["requires"], row["any_of"]) != (was["requires"], was["any_of"]):
			lines.append(f"{label}: prerequisites changed.")
		reworded = [part for part in ("delivers", "acceptance", "note") if row[part] != was[part]]
		if reworded:
			lines.append(f"{label}: {' and '.join(reworded)} reworded.")
		if row["opted_in"] != was["opted_in"]:
			lines.append(f"{label}: {'opted in' if row['opted_in'] else 'no longer opted in'}.")
	for row in old:
		if row["id"] not in {r["id"] for r in new} and not row["withdrawn"]:
			lines.append(f"{row['id']} {row['name']}: removed.")
	return lines
