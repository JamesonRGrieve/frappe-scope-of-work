// SPDX-License-Identifier: AGPL-3.0-or-later
frappe.ui.form.on("Scope of Work", {
	setup(frm) {
		frm.set_query("price_list", () => ({ filters: { selling: 1 } }));
		frm.set_query("item_code", "items", () => ({ filters: { scope_enabled: 1, disabled: 0 } }));
	},

	refresh(frm) {
		draw_preview(frm);
		if (frm.is_new()) {
			return;
		}
		const items = __("Items");
		frm.add_custom_button(__("Add from Catalogue"), () => add_from_catalogue(frm, {}), items);
		frm.add_custom_button(__("Add Client Requests"), () => add_from_catalogue(frm, { requested: 1 }), items);
		frm.add_custom_button(__("Add Recommendations"), () => add_from_catalogue(frm, { recommended: 1 }), items);
		frm.add_custom_button(__("Opt In Requests and Recommendations"), () => call(frm, "opt_in_highlights"), items);
		frm.add_custom_button(__("Refresh Prices"), () => call(frm, "refresh_rates"), items);

		const docs = __("Documents");
		frm.add_custom_button(__("Download Document (Markdown)"), () => download(frm, "md"), docs);
		frm.add_custom_button(__("Download Drawing (SVG)"), () => download(frm, "svg"), docs);
		frm.add_custom_button(__("Attach Both to this Scope"), () => call(frm, "attach_files"), docs);
		if (!frm.doc.quotation && !frm.doc.contract) {
			frm.add_custom_button(__("Make Draft Quotation and Contract"), () => make_drafts(frm), docs);
		}
	},
});

function call(frm, method, args = {}) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the scope first."));
		return;
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
				call(frm, "add_items", { item_codes: selections, ...flags });
			}
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
