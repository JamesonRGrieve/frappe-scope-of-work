# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scope-of-work tech tree as plain data: checks, layout, and the two outputs (SVG drawing, Markdown document).

Nothing here touches Frappe, so the whole form can be tested and rendered without a bench. `scope.py` builds a
`Scope` from the DocTypes; this module never reads the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from html import escape

ONE_TIME = "One-time"
PER_MONTH = "Per month"
LATER_LETTER = "X"
ID_PATTERN = re.compile(r"^([A-Z])(\d+)([a-z]?)$")


class TreeError(ValueError):
	"""The tree breaks a rule of the form. `problems` lists every fault found, not just the first."""

	def __init__(self, problems: list[str]):
		super().__init__("; ".join(problems))
		self.problems = problems


@dataclass
class Branch:
	letter: str
	name: str
	colour: str


@dataclass
class Entry:
	id: str
	name: str
	branch: str  # branch letter
	requires: list[str] = field(default_factory=list)
	any_of: list[str] = field(default_factory=list)  # needs at least one of these as well as `requires`
	delivers: list[str] = field(default_factory=list)
	acceptance: str = ""
	note: str = ""
	later: bool = False
	is_choice: bool = False  # a choice group: one slot, its options are entries with choice_of set
	choice_of: str = ""
	default_option: bool = False
	charge: str = ONE_TIME
	rate: Decimal | None = None  # None prints TBS
	required: bool = False
	requested: bool = False  # the client asked for it
	recommended: bool = False  # Zephyrex recommends it
	reason: str = ""  # why it is recommended, or what the client asked for
	opted_in: bool = False
	delivered: bool = False  # delivered under an earlier scope
	withdrawn: bool = False
	row: float | None = None  # manual layout override


@dataclass
class Scope:
	title: str
	prepared_for: str
	date: str
	entries: list[Entry]
	branches: list[Branch]
	prepared_by: str = "Zephyrex Technologies Limited"
	signatory: str = ""
	status: str = "Draft"
	currency: str = "CAD"
	tax_note: str = "before tax"
	intro: str = ""
	provides: list[tuple[str, str]] = field(default_factory=list)  # (item IDs, what the client provides)
	provides_general: str = ""
	exclusions: list[str] = field(default_factory=list)
	assumptions: list[str] = field(default_factory=list)
	changes: list[str] = field(default_factory=list)
	open_points: list[str] = field(default_factory=list)
	payment_terms: str = ""
	svg_name: str = "scope-tree.svg"


# ---- the tree's rules


class Tree:
	"""A checked scope: lookups, tiers and rows. Building one raises TreeError for a broken tree."""

	def __init__(self, scope: Scope):
		self.scope = scope
		self.entries = [e for e in scope.entries if not e.withdrawn]
		self.by_id = {e.id: e for e in self.entries}
		self.branches = {b.letter: b for b in scope.branches}
		self.branch_order = {b.letter: i for i, b in enumerate(scope.branches)}
		self.options = {e.id: [o for o in self.entries if o.choice_of == e.id] for e in self.entries if e.is_choice}
		self.check()
		self.tier = self._tiers()
		self.row = self._rows()

	def parents(self, entry: Entry) -> list[str]:
		return entry.requires + entry.any_of

	def check(self) -> None:
		problems = []
		seen: set[str] = set()
		for e in self.scope.entries:
			if e.id in seen:
				problems.append(f"{e.id} is used twice")
			seen.add(e.id)
			if not ID_PATTERN.match(e.id):
				problems.append(
					f"{e.id} is not an item ID (a capital letter, a number, and a lowercase letter for an option)"
				)
		for e in self.entries:
			if e.branch not in self.branches:
				problems.append(f"{e.id} is in branch {e.branch!r}, which has no letter and colour")
			for p in self.parents(e):
				if p not in self.by_id:
					problems.append(f"{e.id} requires {p}, which is not on the tree")
				elif self.by_id[p].choice_of:
					problems.append(f"{e.id} requires {p}; require the choice group {self.by_id[p].choice_of} instead")
				elif self.by_id[p].later and not e.later:
					problems.append(
						f"{e.id} requires {p}, a later item; a priced item cannot depend on an unpriced one"
					)
			if e.choice_of:
				group = self.by_id.get(e.choice_of)
				if group is None or not group.is_choice:
					problems.append(f"{e.id} is an option of {e.choice_of}, which is not a choice group")
				if e.requires or e.any_of:
					problems.append(f"{e.id} is an option; its prerequisites belong on the group {e.choice_of}")
			if e.is_choice and e.later:
				problems.append(f"{e.id} is a choice group and cannot be a later item")
			if e.later and (e.opted_in or e.rate is not None):
				problems.append(f"{e.id} is a later item and cannot be priced or opted into")
		for gid, options in self.options.items():
			if len(options) < 2:
				problems.append(f"choice group {gid} needs at least two options")
			defaults = [o.id for o in options if o.default_option]
			if len(defaults) > 1:
				problems.append(f"choice group {gid} has more than one default option: {', '.join(defaults)}")
			opted = [o.id for o in options if o.opted_in]
			if len(opted) > 1:
				problems.append(f"choice group {gid} has more than one option opted in: {', '.join(opted)}")
		problems += self._cycles()
		if not problems:
			problems += self._opt_in_problems()
		if problems:
			raise TreeError(problems)

	def _cycles(self) -> list[str]:
		state: dict[str, int] = {}
		found: list[str] = []

		def visit(eid: str, path: list[str]) -> None:
			if state.get(eid) == 2 or eid not in self.by_id:
				return
			if state.get(eid) == 1:
				found.append("prerequisites go round in a circle: " + " → ".join(path[path.index(eid) :] + [eid]))
				return
			state[eid] = 1
			for p in self.parents(self.by_id[eid]):
				visit(p, path + [eid])
			state[eid] = 2

		for e in self.entries:
			visit(e.id, [])
		return found

	def taken(self, eid: str) -> bool:
		"""Opted into or already delivered. A choice group is taken when one of its options is; a required group
		always is, since one of its options will be, whichever is chosen."""
		e = self.by_id[eid]
		if e.is_choice:
			return e.delivered or e.required or any(self.taken(o.id) for o in self.options[eid])
		return e.opted_in or e.delivered or e.required

	def counted(self, e: Entry) -> bool:
		"""Charged on this scope: opted in or required, and for a choice group nobody has picked, the default."""
		if e.is_choice or e.later or e.delivered:
			return False
		if e.choice_of:
			options = self.options[e.choice_of]
			if any(o.opted_in or o.delivered for o in options):
				return e.opted_in
			return e.default_option and (self.by_id[e.choice_of].required or self.by_id[e.choice_of].opted_in)
		return e.opted_in or e.required

	def _opt_in_problems(self) -> list[str]:
		problems = []
		for e in self.entries:
			if not (e.opted_in or e.required) or e.choice_of:
				continue
			missing = [p for p in e.requires if not self.taken(p)]
			if e.any_of and not any(self.taken(p) for p in e.any_of):
				missing.append(" or ".join(e.any_of))
			if missing and not e.is_choice:
				problems.append(
					f"{e.id} is opted in but needs {', '.join(missing)}, which is not opted in or delivered"
				)
		return problems

	# ---- layout: tiers from prerequisites, rows packed column by column

	def _tiers(self) -> dict[str, int]:
		tier: dict[str, int] = {}

		def of(eid: str) -> int:
			if eid not in tier:
				e = self.by_id[eid]
				if e.choice_of:
					tier[eid] = of(e.choice_of)
				else:
					parents = self.parents(e)
					tier[eid] = 1 + max(of(p) for p in parents) if parents else 0
			return tier[eid]

		for e in self.entries:
			of(e.id)
		return tier

	def height(self, e: Entry) -> float:
		return GROUP_HEAD + len(self.options[e.id]) + GROUP_FOOT if e.is_choice else 1.0

	def _rows(self) -> dict[str, float]:
		row: dict[str, float] = {}
		columns: dict[int, list[Entry]] = {}
		for e in self.entries:
			if not e.choice_of:
				columns.setdefault(self.tier[e.id], []).append(e)
		index = {e.id: i for i, e in enumerate(self.entries)}
		for tier in sorted(columns):
			column = columns[tier]
			desired: dict[str, float] = {}
			if tier == 0:
				column.sort(key=lambda e: (self.branch_order.get(e.branch, 99), index[e.id]))
				cursor = 0.0
				for e in column:
					desired[e.id] = cursor
					cursor += self.height(e) + GAP
			else:
				# Children of one item stay together, centred on it where there is room; clusters keep their
				# parents' order, so lines cross as little as a column-by-column layout allows.
				clusters: dict[str, list[Entry]] = {}
				for e in column:
					clusters.setdefault(self.parents(e)[0], []).append(e)
				ordered: list[Entry] = []
				for parent_id in sorted(clusters, key=lambda p: (row[p], index[p])):
					group = sorted(
						clusters[parent_id], key=lambda e: (self.branch_order.get(e.branch, 99), index[e.id])
					)
					centre = row[parent_id] + (self.height(self.by_id[parent_id]) - 1) / 2
					span = sum(self.height(e) for e in group) + GAP * (len(group) - 1)
					start = centre + 0.5 - span / 2
					for e in group:
						desired[e.id] = start
						start += self.height(e) + GAP
					ordered += group
				column[:] = ordered
			cursor = float("-inf")
			for e in column:
				top = e.row if e.row is not None else max(desired[e.id], cursor)
				row[e.id] = top
				cursor = top + self.height(e) + GAP
				for n, option in enumerate(self.options.get(e.id, [])):
					row[option.id] = top + GROUP_HEAD + n
		lowest = min(row.values(), default=0.0)
		row = {k: v - lowest for k, v in row.items()}
		self._check_overlaps(row)
		return row

	def _check_overlaps(self, row: dict[str, float]) -> None:
		problems = []
		boxes = sorted(
			(self.tier[e.id], row[e.id], row[e.id] + self.height(e), e.id) for e in self.entries if not e.choice_of
		)
		for a, b in zip(boxes, boxes[1:], strict=False):
			if a[0] == b[0] and b[1] < a[2] - 1e-9:
				problems.append(f"{a[3]} and {b[3]} overlap in the drawing (check their manual rows)")
		if problems:
			raise TreeError(problems)

	# ---- reading the tree

	def roots(self) -> list[Entry]:
		return [e for e in self.entries if not e.choice_of and not self.parents(e)]

	def children(self, eid: str) -> list[Entry]:
		return [e for e in self.entries if not e.choice_of and self.parents(e)[:1] == [eid]]

	def unlocks(self, eid: str) -> list[str]:
		return [e.id for e in self.entries if eid in self.parents(e)]

	def priced(self) -> list[Entry]:
		return [e for e in self.entries if not e.later]

	def later(self) -> list[Entry]:
		return [e for e in self.entries if e.later]

	def ordered(self) -> list[Entry]:
		"""Tree order: by tier, then row, with each choice group's options straight after it."""
		top = [e for e in self.entries if not e.choice_of]
		top.sort(key=lambda e: (self.tier[e.id], self.row[e.id]))
		out = []
		for e in top:
			out.append(e)
			out += self.options.get(e.id, [])
		return out


GROUP_HEAD = 0.85
GROUP_FOOT = 0.2
GAP = 0.15


def next_id(used: set[str], letter: str, option_of: str = "") -> str:
	"""The next free item ID in a branch, or the next option letter in a choice group. Retired IDs stay used."""
	if option_of:
		for suffix in "abcdefghijklmnopqrstuvwxyz":
			if option_of + suffix not in used:
				return option_of + suffix
		raise TreeError([f"choice group {option_of} has no option letters left"])
	numbers = [int(m.group(2)) for u in used if (m := ID_PATTERN.match(u)) and m.group(1) == letter and not m.group(3)]
	return f"{letter}{max(numbers, default=0) + 1}"


def requires_text(e: Entry) -> str:
	parts = list(e.requires)
	if e.any_of:
		parts.append(" or ".join(e.any_of))
	return ", ".join(parts) or "none"


def totals_of(tree: Tree) -> dict[str, Decimal]:
	"""Sums of the opted-in, not yet delivered items by how they are charged; empty if any of them has no price."""
	totals: dict[str, Decimal] = {}
	for e in tree.entries:
		if not tree.counted(e):
			continue
		if e.rate is None:
			return {}
		totals[e.charge] = totals.get(e.charge, Decimal(0)) + e.rate
	return dict(sorted(totals.items(), key=lambda kv: (kv[0] != ONE_TIME, kv[0])))


def undecided_groups(tree: Tree) -> list[str]:
	"""Required choice groups with no option opted in, delivered or marked as the default."""
	return [
		gid
		for gid, options in tree.options.items()
		if tree.by_id[gid].required
		and not tree.by_id[gid].delivered
		and not any(o.default_option or o.opted_in or o.delivered for o in options)
	]


def money(value: Decimal | None, currency: str) -> str:
	if value is None:
		return "TBS"
	return f"{currency} {value.quantize(Decimal('0.01')):,}"


# ---- SVG

BOX_W, BOX_H, COL_W, ROW_H, LEFT, TOP = 264, 54, 344, 66, 30, 118
REQUESTED_COLOUR = "#f2b134"
RECOMMENDED_COLOUR = "#5fd39a"
TEXT_W = 7.9  # average width of a bold 14px Helvetica character


def fit(text: str, room: float, size: float = 14, smallest: float = 11) -> tuple[str, float]:
	"""Shrink the font until the text fits the room, then cut it with an ellipsis."""
	while size > smallest and len(text) * TEXT_W * size / 14 > room:
		size -= 0.5
	limit = int(room / (TEXT_W * size / 14))
	if len(text) > limit:
		text = text[: max(limit - 1, 1)].rstrip() + "…"
	return text, size


def svg(tree: Tree) -> str:
	scope = tree.scope
	tiers = max(tree.tier.values(), default=0) + 1
	bottom = max((tree.row[e.id] + tree.height(e) for e in tree.entries if not e.choice_of), default=1)
	width = max(LEFT * 2 + COL_W * (tiers - 1) + BOX_W, 1020)
	height = TOP + ROW_H * bottom + 70

	def xy(e: Entry) -> tuple[float, float]:
		return LEFT + tree.tier[e.id] * COL_W, TOP + tree.row[e.id] * ROW_H

	highlight = any(e.requested or e.recommended for e in tree.entries)
	out = [
		f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height:.0f}" width="{width}" '
		f'height="{height:.0f}" font-family="Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
		f'<title id="t">{escape(scope.title)}: tech tree</title>',
		'<desc id="d">Scope items by tier, left to right. A line joins each item to the items it requires.</desc>',
		f'<rect width="{width}" height="{height:.0f}" fill="#11161c"/>',
		f'<text x="{LEFT}" y="34" fill="#e8edf2" font-size="22" font-weight="bold">{escape(scope.title)}</text>',
		f'<text x="{LEFT}" y="56" fill="#c5ced8" font-size="14">Prepared for {escape(scope.prepared_for)} · '
		f"{escape(scope.date)}</text>",
		f'<text x="{LEFT}" y="78" fill="#9aa7b4" font-size="12">Each item unlocks when everything it is joined to on '
		"its left is taken. Dashed line: a prerequisite from another branch, or one of alternatives. Dashed box: a "
		"later item, not priced here. Bracketed group: choose exactly one.</text>",
	]
	for tier in range(tiers):
		label = "TIER 0: ROOT" if tier == 0 else f"TIER {tier}"
		out.append(
			f'<text x="{LEFT + tier * COL_W + BOX_W / 2}" y="{TOP - 14}" fill="#6f7d8b" font-size="12" '
			f'text-anchor="middle" letter-spacing="1">{label}</text>'
		)
	roots = {e.id for e in tree.roots()}
	for e in tree.entries:
		if e.choice_of:
			continue
		x, y = xy(e)
		for pid in tree.parents(e):
			parent = tree.by_id[pid]
			px, py = xy(parent)
			x1, y1, x2, y2 = px + BOX_W, py + BOX_H / 2, x, y + BOX_H / 2
			if parent.is_choice:
				x1 = px + BOX_W + 12
				y1 = min(max(y2, py + 20), py + tree.height(parent) * ROW_H - 10)
			mid = (x1 + x2) / 2
			path = f"M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
			cross = parent.branch != e.branch and pid not in roots and not parent.is_choice
			colour = tree.branches[e.branch].colour
			dash = ' stroke-dasharray="6 5"' if cross or pid in e.any_of else ""
			out.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2" opacity="0.85"{dash}/>')
	for e in tree.entries:
		out += _box(tree, e, xy)
	ly = height - 30
	lx = LEFT
	for branch in scope.branches:
		if not any(e.branch == branch.letter for e in tree.entries):
			continue
		out.append(f'<rect x="{lx}" y="{ly}" width="14" height="14" rx="3" fill="{branch.colour}"/>')
		out.append(
			f'<text x="{lx + 20}" y="{ly + 12}" fill="#c5ced8" font-size="13">{escape(branch.name)} ({branch.letter})</text>'
		)
		lx += 30 + len(branch.name) * 8 + 30
	if highlight:
		for label, colour in (("Requested by you", REQUESTED_COLOUR), ("Recommended", RECOMMENDED_COLOUR)):
			out.append(
				f'<rect x="{lx}" y="{ly - 1}" width="16" height="16" rx="4" fill="none" stroke="{colour}" stroke-width="3"/>'
			)
			out.append(f'<text x="{lx + 22}" y="{ly + 12}" fill="#c5ced8" font-size="13">{label}</text>')
			lx += 40 + len(label) * 8
	out.append("</svg>")
	return "\n".join(out) + "\n"


def _box(tree: Tree, e: Entry, xy) -> list[str]:
	x, y = xy(e)
	colour = tree.branches[e.branch].colour
	out = []
	if e.is_choice:
		h = tree.height(e) * ROW_H - (ROW_H - BOX_H) + 6
		out.append(
			f'<rect x="{x - 12}" y="{y}" width="{BOX_W + 24}" height="{h:.0f}" rx="12" fill="#141b22" '
			f'stroke="{colour}" stroke-width="2"/>'
		)
		label, size = fit(f"{e.id}  {e.name}", BOX_W - 8)
		out.append(
			f'<text x="{x + 4}" y="{y + 24}" fill="#e8edf2" font-size="{size}" font-weight="bold">{escape(label)}</text>'
		)
		sub = "required · choose one" if e.required else "optional · choose one or none"
		out.append(f'<text x="{x + 4}" y="{y + 41}" fill="#9aa7b4" font-size="12">{sub}</text>')
		return out
	marks = []
	if e.requested:
		marks.append(REQUESTED_COLOUR)
	if e.recommended:
		marks.append(RECOMMENDED_COLOUR)
	for n, mark in enumerate(marks):
		pad = 4 + n * 4
		out.append(
			f'<rect x="{x - pad}" y="{y - pad}" width="{BOX_W + 2 * pad}" height="{BOX_H + 2 * pad}" rx="{8 + pad}" '
			f'fill="none" stroke="{mark}" stroke-width="3"/>'
		)
	tags = []
	if e.requested:
		tags.append(("REQUESTED", REQUESTED_COLOUR))
	if e.recommended:
		tags.append(("RECOMMENDED", RECOMMENDED_COLOUR))
	text_x = x + 20
	if e.choice_of:
		out.append(
			f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="8" fill="#1c2630" stroke="{colour}" stroke-width="2"/>'
		)
		fill = colour if e.opted_in or e.delivered else "none"
		out.append(
			f'<circle cx="{x + 20}" cy="{y + BOX_H / 2}" r="7" fill="{fill}" stroke="{colour}" stroke-width="2"/>'
		)
		text_x = x + 38
		sub = "option · " + e.charge.lower() + (" · default" if e.default_option else "")
		text_colour = "#e8edf2"
	elif e.later:
		out.append(
			f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="8" fill="#161d25" stroke="{colour}" '
			'stroke-width="1.5" stroke-dasharray="5 4"/>'
		)
		text_colour, sub = "#9aa7b4", "later, not priced"
	else:
		out.append(
			f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="8" fill="#1c2630" stroke="{colour}" stroke-width="2"/>'
		)
		out.append(f'<rect x="{x}" y="{y}" width="8" height="{BOX_H}" rx="4" fill="{colour}"/>')
		text_colour = "#e8edf2"
		if e.delivered:
			sub = "delivered"
		elif e.required:
			sub = "required"
		else:
			sub = f"{tree.branches[e.branch].name} · " + ("opted in" if e.opted_in else "opt-in")
	label, size = fit(f"{e.id}  {e.name}", x + BOX_W - 10 - text_x)
	out.append(
		f'<text x="{text_x}" y="{y + 23}" fill="{text_colour}" font-size="{size}" font-weight="bold">{escape(label)}</text>'
	)
	out.append(f'<text x="{text_x}" y="{y + 42}" fill="#9aa7b4" font-size="12">{escape(sub)}</text>')
	tx = x + BOX_W - 8
	for text, mark in reversed(tags):
		w = len(text) * 7.2 + 12
		tx -= w
		out.append(f'<rect x="{tx:.1f}" y="{y + 31}" width="{w:.1f}" height="16" rx="8" fill="{mark}"/>')
		out.append(
			f'<text x="{tx + w / 2:.1f}" y="{y + 43}" fill="#11161c" font-size="10" font-weight="bold" '
			f'text-anchor="middle">{text}</text>'
		)
		tx -= 4
	return out


# ---- Markdown

STATUS_TEXT = {
	"Draft": "Draft for review. Not an offer until priced and issued with a Quotation.",
	"Sent": "Issued with a Quotation. Item IDs are fixed.",
	"Accepted": "Accepted by the client.",
}


def markdown(tree: Tree) -> str:
	s = tree.scope
	entries = tree.ordered()
	priced = [e for e in entries if not e.later]
	later = [e for e in entries if e.later]
	groups = [e for e in entries if e.is_choice]
	present = [b for b in s.branches if any(e.branch == b.letter for e in tree.entries)]
	lines = [
		f"# Scope of Work: {s.title}",
		"",
		f"**Prepared by:** {s.prepared_by}",
		f"**Prepared for:** {s.prepared_for}",
		f"**Date:** {s.date}",
		f"**Status:** {STATUS_TEXT.get(s.status, s.status)}",
		"",
		'"TBS" marks a point still to be specified. Each one is listed again under *Open Points*.',
		"",
	]
	n = 0

	def section(title: str) -> None:
		nonlocal n
		n += 1
		lines.extend([f"## {n}. {title}", ""])

	section("How this scope works")
	if s.intro:
		lines += [s.intro, ""]
	lines += [
		"The work is a tree of items, like a technology tree in a strategy game. Each item is a small, complete",
		"piece of work with its own price and its own acceptance. An item can be taken once every item it",
		"requires has been delivered. The client opts into the items it wants now; anything left out stays on",
		"the tree and can be taken later, at the price then quoted, without redoing what is already built.",
		"",
	]
	required = [e for e in priced if e.required and not e.choice_of]
	if required:
		lines.append(
			"- **Required:** " + ", ".join(f"{e.id} {e.name}" for e in required) + ". Everything else is opt-in."
		)
	for g in groups:
		opts = ", ".join(f"{o.id} {o.name}" for o in tree.options[g.id])
		kind = "exactly one is taken" if g.required else "at most one is taken"
		lines.append(
			f"- **{g.id} {g.name} is a choice group:** a slot with several options ({opts}), and {kind}. "
			f"An item that requires {g.id} is satisfied by whichever option is taken."
		)
	lines.append(
		"- **Branches** group items that build on each other: "
		+ ", ".join(f"{b.name} ({b.letter})" for b in present)
		+ "."
	)
	cross = [
		e
		for e in priced
		if len({tree.by_id[p].branch for p in tree.parents(e)} | {e.branch}) > 1 and len(tree.parents(e)) > 1
	]
	if cross:
		e = cross[0]
		lines.append(
			f"- **Some items need prerequisites from another branch.** {e.id} {e.name} needs "
			+ " and ".join(f"{p} {tree.by_id[p].name}" for p in tree.parents(e))
			+ "."
		)
	lines += [
		"- **Tiers** count the steps from the root: a Tier 2 item has a Tier 1 item in front of it.",
		"- Each item is invoiced when it is accepted.",
		"",
	]

	requested = [e for e in entries if e.requested]
	recommended = [e for e in entries if e.recommended]
	if requested or recommended:
		section("Your requests and our recommendations")
		lines += [
			"Items you asked for are outlined in amber on the drawing; items Zephyrex recommends are outlined in green.",
			"",
			"| Item | Name | Requested by you | Recommended | Why |",
			"|---|---|---|---|---|",
		]
		for e in entries:
			if e.requested or e.recommended:
				lines.append(
					f"| {e.id} | {e.name} | {'✔' if e.requested else ''} | {'✔' if e.recommended else ''} | {e.reason} |"
				)
		missing = sorted(
			{p for e in requested for p in e.requires if not tree.by_id[p].requested and not tree.taken(p)}
			- {e.id for e in requested}
		)
		if missing:
			lines += ["", "Your requests also need: " + ", ".join(f"{p} {tree.by_id[p].name}" for p in missing) + "."]
		lines.append("")

	section("The tree")
	lines += [
		f"The drawn tree is in `{s.svg_name}`, beside this document. The same tree in text:",
		"",
		"```",
	]

	def draw(e: Entry, prefix: str, last: bool, under: str | None) -> None:
		top = under is None
		others = [p for p in e.requires if p != under]
		alternatives = [p for p in e.any_of if p != under]
		also = f"   (also needs {', '.join(others)})" if others else ""
		if alternatives:
			also += (
				f"   (or {' or '.join(alternatives)} instead of {under})"
				if under in e.any_of
				else (f"   (and one of {' or '.join(alternatives)})")
			)
		tag = "  [later]" if e.later else ""
		tag += "  [requested]" if e.requested else ""
		tag += "  [recommended]" if e.recommended else ""
		choose = ("  (required: choose one)" if e.required else "  (choose one or none)") if e.is_choice else ""
		lines.append(f"{prefix}{'' if top else ('└─ ' if last else '├─ ')}{e.id} {e.name}{choose}{tag}{also}")
		pad = prefix + ("" if top else ("   " if last else "│  "))
		for option in tree.options.get(e.id, []):
			mark = "◉" if option.opted_in or option.delivered else "◯"
			flags = ("  [requested]" if option.requested else "") + ("  [recommended]" if option.recommended else "")
			lines.append(f"{pad}   {mark} {option.id} {option.name}{flags}")
		kids = sorted(tree.children(e.id), key=lambda c: (tree.tier[c.id], tree.row[c.id]))
		for i, child in enumerate(kids):
			draw(child, pad, i == len(kids) - 1, e.id)

	for root in sorted(tree.roots(), key=lambda r: tree.row[r.id]):
		draw(root, "", True, None)
	lines += [
		"```",
		"",
		'An item is shown under the first item it requires; "also needs" names its other prerequisites.',
		"",
	]

	section("Every item")
	lines += ["| Item | Name | Branch | Tier | Requires | Unlocks |", "|---|---|---|---|---|---|"]
	for e in entries:
		name = e.name + (" *(later)*" if e.later else "")
		if e.is_choice:
			name += f" *(choose one: {', '.join(o.id for o in tree.options[e.id])})*"
		if e.choice_of:
			name += f" *(option of {e.choice_of})*"
		requires = "none" if e.choice_of else requires_text(e)
		lines.append(
			f"| {e.id} | {name} | {tree.branches[e.branch].name} | {tree.tier[e.id]} | {requires} | "
			f"{', '.join(tree.unlocks(e.id)) or 'none'} |"
		)
	lines.append("")

	section("What each item delivers")
	lines.append("An item is complete when its acceptance is demonstrated to the client on the client's own system.")
	for branch in present:
		members = [e for e in priced if e.branch == branch.letter]
		if not members:
			continue
		lines += ["", f"### {branch.name} branch"]
		for e in members:
			if e.is_choice:
				opts = ", ".join(o.id for o in tree.options[e.id])
				lines += ["", f"#### {e.id}. {e.name} (choose one)", ""]
				if e.note:
					lines += [e.note, ""]
				lines.append(f"Options: {opts}.")
				continue
			heading = f"*Option of {e.choice_of}.*" if e.choice_of else f"*Requires: {requires_text(e)}.*"
			lines += ["", f"#### {e.id}. {e.name}", "", heading]
			if e.delivers:
				lines += [""] + [f"- {text}" for text in e.delivers]
			lines += ["", f"**Acceptance:** {e.acceptance or 'TBS'}"]
			if e.note:
				lines += ["", f"**Note:** {e.note}"]
	lines.append("")

	if later:
		section("Later items (on the tree, not priced here)")
		lines += [
			"These are where the tree can grow next. Each is scoped and quoted when the client wants it.",
			"",
			"| Item | Name | Requires |",
			"|---|---|---|",
		]
		lines += [f"| {e.id} | {e.name} | {requires_text(e)} |" for e in later]
		lines.append("")

	if s.provides_general or s.provides:
		section("What the client provides")
	if s.provides_general:
		lines += [s.provides_general, ""]
	if s.provides:
		lines += ["| Item | The client provides |", "|---|---|"]
		lines += [f"| {ids} | {text} |" for ids, text in s.provides]
		lines.append("")

	if s.exclusions:
		section("Not included in any item")
		lines += [f"- {x}" for x in s.exclusions] + [""]
	if s.assumptions:
		section("Assumptions")
		lines += [f"- {x}" for x in s.assumptions] + [""]

	section("Price")
	lines += [
		f"Fixed price per item, in {s.currency}, {s.tax_note}. Only the items the client opts into are",
		"charged. An item can be ticked only if every item in its Requires column is ticked or already delivered.",
		"In a choice group (◯) exactly one option is marked.",
		"",
		"| Item | Name | Requires | Price | Charged | Opt-in |",
		"|---|---|---|---|---|---|",
	]
	for e in priced:
		if e.is_choice:
			lines.append(
				f"| {e.id} | {e.name}: choose one | {requires_text(e)} | | | {'Required' if e.required else ''} |"
			)
			continue
		if e.delivered:
			mark = "Delivered"
		elif e.required:
			mark = "Required"
		elif e.choice_of:
			mark = "◉" if e.opted_in else "◯"
		else:
			mark = "☑" if e.opted_in else "☐"
		name = f"↳ {e.name}" if e.choice_of else e.name
		if e.choice_of and e.default_option:
			name += " *(default)*"
		requires = "" if e.choice_of else requires_text(e)
		lines.append(f"| {e.id} | {name} | {requires} | {money(e.rate, s.currency)} | {e.charge.lower()} | {mark} |")
	totals = totals_of(tree)
	if totals:
		lines += [
			"",
			"Total of the items marked: "
			+ ", ".join(f"{money(v, s.currency)} {k.lower()}" for k, v in totals.items())
			+ ".",
		]
	lines += [
		"",
		f"Payment terms: {s.payment_terms or 'TBS'}. Schedule: TBS, agreed per item when it is opted into.",
		"",
	]

	section("Changes and warranty")
	changes = s.changes or [
		"An item not opted into at signing can be added later by written agreement, at the price then quoted.",
		"Work that is not an item on this tree is quoted separately and starts only on written agreement.",
		"Defects in an accepted item reported within TBS days of its acceptance are corrected at no charge.",
	]
	lines += [f"- {x}" for x in changes] + [""]

	section("Open Points")
	points = list(s.open_points)
	billable = [e for e in priced if not e.is_choice and not e.delivered]
	unpriced = [e.id for e in billable if e.rate is None]
	if unpriced and len(unpriced) == len(billable):
		points.insert(0, "Price of each item.")
	elif unpriced:
		points.insert(0, "Price of " + ", ".join(unpriced) + ".")
	for gid in undecided_groups(tree):
		points.append(f"Which {gid} option the quote is built on (its default).")
	if not s.payment_terms:
		points.append("Payment terms.")
	if points:
		lines += [f"{i}. {p}" for i, p in enumerate(points, 1)]
	else:
		lines.append("None.")
	lines.append("")

	section("Acceptance of this scope")
	lines += [
		"The client's opt-ins are the boxes ticked in the Price table.",
		"",
		f"| | Client | {s.prepared_by} |",
		"|---|---|---|",
		f"| Name | | {s.signatory} |",
		"| Signature | | |",
		"| Date | | |",
	]
	return "\n".join(lines) + "\n"
