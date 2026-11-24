# SPDX-License-Identifier: AGPL-3.0-or-later
"""File a scope's document, drawing and PDF into the client's Nextcloud folder and attach them to the owning
Deck card. WebDAV for the files (each one's stored size checked against what was sent), the OCS share API with
share type 12 (a Deck card) for the attachments. The HTTP session is injectable so tests replay Nextcloud."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _

DECK_SHARE = 12
TIMEOUT = 60


class NextcloudError(Exception):
	pass


class Nextcloud:
	def __init__(self, base: str, user: str, password: str, session: Any = None):
		import requests

		self.base = base.rstrip("/")
		self.user = user
		self.session = session or requests.Session()
		self.session.auth = (user, password)

	def dav(self, path: str) -> str:
		return f"{self.base}/remote.php/dav/files/{quote(self.user)}/{quote(path.strip('/'))}"

	def request(self, method: str, url: str, ok: tuple[int, ...], **kwargs) -> Any:
		response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
		if response.status_code not in ok:
			# Never echo the URL's credentials; the session holds them, not the URL.
			raise NextcloudError(f"{method} {url.split('/remote.php')[0]}… answered {response.status_code}")
		return response

	def make_folders(self, path: str) -> None:
		parts = [p for p in path.strip("/").split("/") if p]
		for depth in range(1, len(parts) + 1):
			self.request("MKCOL", self.dav("/".join(parts[:depth])), ok=(201, 405))  # 405: already there

	def put(self, path: str, content: bytes) -> None:
		self.request("PUT", self.dav(path), ok=(201, 204), data=content)

	def size(self, path: str) -> int:
		body = '<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/></d:prop></d:propfind>'
		response = self.request("PROPFIND", self.dav(path), ok=(207,), data=body, headers={"Depth": "0"})
		length = ET.fromstring(response.content).find(".//{DAV:}getcontentlength")
		if length is None or not (length.text or "").isdigit():
			raise NextcloudError(f"no size reported for {path}")
		return int(length.text)

	def ocs(self, method: str, **kwargs) -> Any:
		response = self.request(
			method,
			f"{self.base}/ocs/v2.php/apps/files_sharing/api/v1/shares",
			ok=(200,),
			headers={"OCS-APIRequest": "true", "Accept": "application/json"},
			**kwargs,
		)
		return response.json()["ocs"]["data"]

	def shared_with_card(self, path: str, card: int) -> bool:
		shares = self.ocs("GET", params={"path": "/" + path.strip("/"), "reshares": "true"})
		return any(int(s.get("share_type", -1)) == DECK_SHARE and str(s.get("share_with")) == str(card) for s in shares)

	def share_with_card(self, path: str, card: int) -> None:
		self.ocs("POST", data={"path": "/" + path.strip("/"), "shareType": DECK_SHARE, "shareWith": str(card)})


def card_id(value: str | None) -> int | None:
	"""A Deck card's number from its link (…/deck/board/12/card/397) or the bare number."""
	if not value:
		return None
	match = re.search(r"/card/(\d+)", value) or re.fullmatch(r"\s*(\d+)\s*", value)
	if not match:
		frappe.throw(_("{0} is not a Deck card link or number.").format(value))
	return int(match.group(1))


def folder_for(doc: Any, settings: Any) -> str:
	if doc.nextcloud_folder:
		return doc.nextcloud_folder.strip("/")
	client = re.sub(r'[\\/:*?"<>|]', "", (doc.prepared_for or doc.party or "").split(",")[0]).strip()
	return "/".join(filter(None, [(settings.nextcloud_base_folder or "").strip("/"), client]))


def client_from_settings(session: Any = None) -> Nextcloud:
	settings = frappe.get_single("Scope of Work Settings")
	password = settings.get_password("nextcloud_password", raise_exception=False)
	if not (settings.nextcloud_url and settings.nextcloud_user and password):
		frappe.throw(_("Set the Nextcloud address, user and app password in Scope of Work Settings first."))
	return Nextcloud(settings.nextcloud_url, settings.nextcloud_user, password, session)


def file_scope(doc: Any, nextcloud: Nextcloud | None = None) -> dict[str, Any]:
	"""Write the three files, check each stored size, and attach each to the Deck card once (an existing
	attachment is not duplicated). Returns the folder and what was attached."""
	from scope_of_work import printing, scope
	from scope_of_work import tree as t

	settings = frappe.get_single("Scope of Work Settings")
	nextcloud = nextcloud or client_from_settings()
	tree = scope.build(doc)
	files = {
		scope.MD_NAME.format(name=doc.name): t.markdown(tree).encode(),
		scope.SVG_NAME.format(name=doc.name): t.svg(tree).encode(),
		printing.PDF_NAME.format(name=doc.name): printing.pdf(doc),
	}
	folder = folder_for(doc, settings)
	nextcloud.make_folders(folder)
	card = card_id(doc.deck_card)
	attached = []
	for name, content in files.items():
		path = f"{folder}/{name}"
		nextcloud.put(path, content)
		stored = nextcloud.size(path)
		if stored != len(content):
			raise NextcloudError(f"{name} stored {stored} bytes, sent {len(content)}")
		if card and not nextcloud.shared_with_card(path, card):
			nextcloud.share_with_card(path, card)
			attached.append(name)
	doc.db_set("filed_on", frappe.utils.now_datetime())
	return {"folder": folder, "files": list(files), "attached": attached, "card": card}
