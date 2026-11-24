// SPDX-License-Identifier: AGPL-3.0-or-later
// The client's scope page: ticking enforces prerequisites both ways, and the total follows the ticks.
(() => {
	const { items, key, currency } = window.sow;
	const byId = Object.fromEntries(items.map((i) => [i.id, i]));
	const form = document.getElementById("sow-form");
	const inputs = Object.fromEntries([...form.querySelectorAll("input")].map((el) => [el.value, el]));

	const ticked = (id) => {
		const it = byId[id];
		if (!it) return false;
		if (it.is_choice) {
			return it.delivered || items.some((o) => o.choice_of === id && ticked(o.id));
		}
		if (it.delivered || it.required) return true;
		return Boolean(inputs[id] && inputs[id].checked);
	};
	const satisfied = (it) => {
		const parents = it.choice_of ? byId[it.choice_of] : it;
		const all = parents.requires.every(ticked);
		const one = !parents.any_of.length || parents.any_of.some(ticked);
		return all && one;
	};
	const tick = (id) => {
		const it = byId[id];
		if (!it || it.later) return;
		if (it.is_choice) {
			if (ticked(id)) return;
			const options = items.filter((o) => o.choice_of === id);
			const pick = options.find((o) => o.default_option) || options[0];
			if (pick) tick(pick.id);
			return;
		}
		if (inputs[id] && !inputs[id].disabled) {
			if (it.choice_of) {
				items.filter((o) => o.choice_of === it.choice_of && o.id !== id && inputs[o.id]).forEach((o) => {
					inputs[o.id].checked = false;
				});
			}
			inputs[id].checked = true;
		}
		const parents = it.choice_of ? byId[it.choice_of] : it;
		parents.requires.forEach(tick);
		if (parents.any_of.length && !parents.any_of.some(ticked)) tick(parents.any_of[0]);
	};
	const prune = () => {
		let changed = true;
		while (changed) {
			changed = false;
			items.forEach((it) => {
				const el = inputs[it.id];
				if (el && el.checked && !el.disabled && !satisfied(it)) {
					el.checked = false;
					changed = true;
				}
			});
		}
	};
	const money = (n) =>
		`${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
	const total = () => {
		let once = 0;
		let monthly = 0;
		let tbs = 0;
		items.forEach((it) => {
			if (it.is_choice || it.later || it.delivered || !ticked(it.id)) return;
			if (!it.rate) tbs += 1;
			else if (it.charge === "Per month") monthly += it.rate;
			else once += it.rate;
		});
		let text = `Total: ${money(once)}`;
		if (monthly) text += ` + ${money(monthly)} per month`;
		if (tbs) text += ` (plus ${tbs} item${tbs > 1 ? "s" : ""} still to be priced)`;
		document.getElementById("sow-total").textContent = text;
	};
	form.addEventListener("change", (event) => {
		const el = event.target;
		if (el.checked) tick(el.value);
		prune();
		total();
	});
	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		const msg = document.getElementById("sow-msg");
		const ids = items.filter((it) => !it.is_choice && inputs[it.id] && inputs[it.id].checked).map((it) => it.id);
		const body = new URLSearchParams({ key, ids: JSON.stringify(ids) });
		const response = await fetch("/api/method/scope_of_work.api.client_opt_in", {
			method: "POST",
			headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" },
			body,
		});
		const data = await response.json().catch(() => ({}));
		msg.className = response.ok ? "msg" : "msg err";
		if (response.ok) {
			msg.textContent = "Saved. Thank you: we will be in touch.";
		} else {
			let text = "Could not save.";
			try {
				text = JSON.parse(JSON.parse(data._server_messages)[0]).message.replace(/<br>/g, "; ");
			} catch (e) {
				/* keep the plain message */
			}
			msg.textContent = text;
		}
	});
	total();
})();
