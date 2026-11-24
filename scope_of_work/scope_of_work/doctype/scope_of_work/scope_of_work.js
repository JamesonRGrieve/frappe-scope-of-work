// SPDX-License-Identifier: AGPL-3.0-or-later
frappe.ui.form.on("Scope of Work", {
	setup(frm) {
		frm.set_query("price_list", () => ({ filters: { selling: 1 } }));
		frm.set_query("item_code", "items", () => ({ filters: { scope_enabled: 1, disabled: 0 } }));
		frm.set_query("stack", "items", () => ({}));
	},

	refresh(frm) {
		draw_preview(frm);
		if (frm.is_new()) {
			return;
		}
		if (frm.doc.below_cost) {
			frm.dashboard.add_comment(__("Priced below internal cost: {0}", [frm.doc.below_cost]), "red", true);
		}
		const items = __("Items");
		frm.add_custom_button(__("Add from Catalogue"), () => add_from_catalogue(frm, {}), items);
		frm.add_custom_button(__("Add Client Requests"), () => add_from_catalogue(frm, { requested: 1 }), items);
		frm.add_custom_button(__("Add Recommendations"), () => add_from_catalogue(frm, { recommended: 1 }), items);
		frm.add_custom_button(__("Add Package"), () => add_package(frm), items);
		frm.add_custom_button(__("Suggestions"), () => show_suggestions(frm, true), items);
		frm.add_custom_button(__("Opt In Requests and Recommendations"), () => call(frm, "opt_in_highlights"), items);
		frm.add_custom_button(__("Refresh Prices"), () => call(frm, "refresh_rates"), items);

		const docs = __("Documents");
		frm.add_custom_button(__("Download PDF"), () => download_pdf(frm), docs);
		frm.add_custom_button(__("Download Document (Markdown)"), () => download(frm, "md"), docs);
		frm.add_custom_button(__("Download Drawing (SVG)"), () => download(frm, "svg"), docs);
		frm.add_custom_button(__("Attach All to this Scope"), () => call(frm, "attach_files"), docs);
		frm.add_custom_button(__("File to Nextcloud and Deck"), () => file_to_nextcloud(frm), docs);
		frm.add_custom_button(__("Record Revision"), () => call(frm, "record_revision"), docs);
		if (!frm.doc.quotation && !frm.doc.contract) {
			frm.add_custom_button(__("Make Draft Quotation and Contract"), () => make_drafts(frm), docs);
		}

		const client = __("Client");
		frm.add_custom_button(
			frm.doc.client_link ? __("New Client Link") : __("Share with Client"),
			() => share(frm),
			client
		);
		if (frm.doc.client_link) {
			frm.add_custom_button(__("Copy Client Link"), () => frappe.utils.copy_to_clipboard(frm.doc.client_link), client);
			frm.add_custom_button(__("Revoke Client Link"), () => call(frm, "revoke_client_link"), client);
		}

		if (frm.doc.status === "Accepted") {
			const delivery = __("Delivery");
			if (!frm.doc.project) {
				frm.add_custom_button(__("Make Project"), () => call(frm, "make_project"), delivery);
			}
			if (!frm.doc.subscription && frm.doc.party_type === "Customer") {
				frm.add_custom_button(__("Make Subscription"), () => make_subscription(frm), delivery);
			}
		}
	},
});

function call(frm, method, args = {}) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the scope first."));
		return Promise.resolve();
	}
	return frappe.call({
		method: `scope_of_work.api.${method}`,
		args: { name: frm.doc.name, ...args },
		freeze: true,
		callback: () => frm.reload_doc(),
	});
}

function add_from_catalogue(frm, flags) {
	new frappe.ui.form.MultiSelectDialog({
		doctype: "Item",
		target: frm,
		setters: { item_group: null },
		add_filters_group: 1,
		get_query: () => ({ filters: { scope_enabled: 1, disabled: 0 } }),
		action(selections) {
			this.dialog.hide();
			if (selections && selections.length) {
				call(frm, "add_items", { item_codes: selections, ...flags }).then(() => show_suggestions(frm, false));
			}
		},
	});
}

function add_package(frm) {
	frappe.prompt(
		{ fieldname: "package", fieldtype: "Link", options: "Scope Package", label: __("Package"), reqd: 1 },
		({ package: pkg }) => call(frm, "add_package", { package: pkg }).then(() => show_suggestions(frm, false)),
		__("Add Package")
	);
}

function show_suggestions(frm, always) {
	frappe.call({
		method: "scope_of_work.api.suggestions",
		args: { name: frm.doc.name },
		callback: ({ message }) => {
			const found = message || [];
			if (!found.length) {
				if (always) frappe.msgprint(__("No suggestions: nothing on this scope is often taken with an item missing from it."));
				return;
			}
			const dialog = new frappe.ui.Dialog({
				title: __("Often taken with what is on this scope"),
				fields: [
					{
						fieldname: "picked",
						fieldtype: "Table",
						cannot_add_rows: true,
						in_place_edit: true,
						data: found.map((s) => ({
							add: 0,
							item_code: s.item_code,
							item_name: s.item_name,
							because: s.because.join(", "),
							reason: s.reasons.join("; "),
						})),
						fields: [
							{ fieldname: "add", fieldtype: "Check", label: __("Add"), in_list_view: 1, columns: 1 },
							{ fieldname: "item_name", fieldtype: "Data", label: __("Item"), in_list_view: 1, read_only: 1, columns: 3 },
							{ fieldname: "because", fieldtype: "Data", label: __("Because of"), in_list_view: 1, read_only: 1, columns: 2 },
							{ fieldname: "reason", fieldtype: "Data", label: __("Why"), in_list_view: 1, read_only: 1, columns: 4 },
							{ fieldname: "item_code", fieldtype: "Data", hidden: 1 },
						],
					},
				],
				primary_action_label: __("Add as Recommendations"),
				primary_action({ picked }) {
					const codes = (picked || []).filter((r) => r.add).map((r) => r.item_code);
					dialog.hide();
					if (codes.length) call(frm, "add_items", { item_codes: codes, recommended: 1 });
				},
			});
			dialog.show();
		},
	});
}

function download(frm, kind) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the scope first."));
		return;
	}
	const query = new URLSearchParams({ name: frm.doc.name, kind });
	window.open(`/api/method/scope_of_work.api.download?${query}`);
}

function download_pdf(frm) {
	// The app renders its own self-contained PDF: no stylesheet fetched back from the site's hostname.
	download(frm, "pdf");
}

function file_to_nextcloud(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the scope first."));
		return;
	}
	frappe.call({
		method: "scope_of_work.api.file_to_nextcloud",
		args: { name: frm.doc.name },
		freeze: true,
		freeze_message: __("Filing to Nextcloud…"),
		callback: ({ message }) => {
			frm.reload_doc();
			const attached = message.attached.length ? __("attached to card {0}: {1}", [message.card, message.attached.join(", ")]) : __("no new Deck attachments");
			frappe.msgprint(__("Filed {0} file(s) in {1}; {2}.", [message.files.length, message.folder, attached]));
		},
	});
}

function share(frm) {
	const go = () =>
		frappe.call({
			method: "scope_of_work.api.share_with_client",
			args: { name: frm.doc.name },
			callback: ({ message }) => {
				frm.reload_doc();
				frappe.msgprint({
					title: __("Client page"),
					message: __("Send this link to the client. Anyone with it can see the scope and tick items.<br><br><a href='{0}' target='_blank'>{0}</a>", [message]),
				});
			},
		});
	if (frm.doc.client_link) {
		frappe.confirm(__("Make a new link? The current one stops working."), go);
	} else {
		go();
	}
}

function make_subscription(frm) {
	frappe.prompt(
		{ fieldname: "start_date", fieldtype: "Date", label: __("Billing starts"), reqd: 1, default: frappe.datetime.get_today() },
		({ start_date }) => call(frm, "make_subscription", { start_date }),
		__("Make Subscription"),
		__("Make (invoices stay drafts)")
	);
}

function make_drafts(frm) {
	frappe.confirm(
		__("Make a draft Quotation (and, for a Customer, a draft Contract) from the opted-in items? Nothing is submitted."),
		() =>
			frappe.call({
				method: "scope_of_work.api.make_drafts",
				args: { name: frm.doc.name },
				freeze: true,
				callback: ({ message }) => {
					frm.reload_doc();
					const made = [message.quotation, message.contract].filter(Boolean).join(", ");
					frappe.show_alert({ message: __("Drafts made: {0}", [made]), indicator: "green" });
				},
			})
	);
}

function draw_preview(frm) {
	const wrapper = frm.get_field("tree_preview").$wrapper;
	if (frm.is_new() || !(frm.doc.items || []).length) {
		wrapper.empty();
		return;
	}
	frappe.call({
		method: "scope_of_work.api.preview",
		args: { name: frm.doc.name },
		error_handlers: { ValidationError: () => wrapper.empty() },
		callback: ({ message }) => {
			const box = $('<div style="overflow:auto;max-height:80vh;border-radius:8px"></div>');
			box.html(message);
			box.find("svg").css({ maxWidth: "none" });
			wrapper.empty().append(box);
		},
	});
}
