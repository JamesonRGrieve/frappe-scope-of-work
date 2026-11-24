# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scope as one printable page: the drawing first, then the document. Used by the "Scope of Work" print
format (and so the desk's Print and PDF) and by the PDF attached beside the Markdown and SVG files."""

from __future__ import annotations

import re

import frappe
from frappe.utils import md_to_html

from scope_of_work import scope
from scope_of_work import tree as t

PDF_NAME = "{name} scope.pdf"

STYLE = """
<style>
.sow { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #1d232a; line-height: 1.4; }
.sow h1 { font-size: 18pt; margin: 0 0 8pt; }
.sow h2 { font-size: 13pt; margin: 16pt 0 6pt; border-bottom: 1px solid #c9d1d9; padding-bottom: 2pt; }
.sow h3 { font-size: 11.5pt; margin: 12pt 0 4pt; }
.sow h4 { font-size: 10.5pt; margin: 10pt 0 3pt; }
.sow table { border-collapse: collapse; width: 100%; margin: 6pt 0; page-break-inside: auto; }
.sow tr { page-break-inside: avoid; }
.sow th, .sow td { border: 1px solid #c9d1d9; padding: 3pt 5pt; text-align: left; vertical-align: top; }
.sow th { background: #eef2f6; }
.sow pre { font-size: 8.5pt; background: #f6f8fa; padding: 6pt; white-space: pre-wrap; }
.sow .drawing { page-break-after: always; }
.sow .drawing svg { width: 100%; height: auto; }
</style>
"""


def html(doc) -> str:
	tree = scope.build(doc)
	drawing = t.svg(tree)
	drawing = re.sub(r'(<svg[^>]*?) width="\d+" height="\d+"', r"\1", drawing, count=1)
	body = md_to_html(t.markdown(tree))
	return f'{STYLE}<div class="sow"><div class="drawing">{drawing}</div>{body}</div>'


def scope_html(name: str) -> str:
	"""Jinja method for the print format."""
	doc = frappe.get_doc("Scope of Work", name)
	doc.check_permission("read")
	return html(doc)


def pdf(doc) -> bytes:
	from frappe.utils.pdf import get_pdf

	return get_pdf(
		f"<html><head><meta charset='utf-8'></head><body>{html(doc)}</body></html>",
		{"orientation": "Landscape", "page-size": "A4"},
	)
