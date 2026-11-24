# frappe-scope-of-work — Agent Operating Guide

AGPL-3.0-or-later Frappe v16 app (Python 3.14): per-client scopes of work as tech trees, built from a
catalogue of billable ERPNext Items. The procedure it implements is Zephyrex SOP → *Agent Operating
Standards* → *Scopes of Work*; this file holds only what is specific to this repo.

**The repo is public code; the catalogue and every client's scope are private data in the ERP.** Never commit
item wording, prices, client names or a generated scope. Tests use made-up `_Test SOW` items only.

## Model

- `tree.py`: pure rules, no Frappe. `Tree` checks a scope (IDs, prerequisites, choice groups, cycles, opt-ins),
  works out tiers (1 + highest prerequisite) and rows (children clustered around their first prerequisite),
  and `svg()` / `markdown()` render it. Every rule of the form lives here.
- `install.py`: the catalogue fields on Item (`scope_*`, tab *Scope of Work*) and Item Group (branch letter,
  colour, order), created by `after_install` / `after_migrate`.
- `scope.py`: catalogue → scope rows (`add_items`, IDs via `tree.next_id`), scope → `tree.Scope`, the draft
  Quotation and Contract (`make_drafts`), attachments.
- `api.py`: the whitelisted methods the Scope of Work form calls.
- A rate of zero is printed `TBS`; prices are never inferred.
- Once a scope is Sent or Accepted, `keep_sent_ids` refuses any change to an existing row's ID or item.

## Testing

- `tools/test-bench.sh up|test|serve|down` (podman, ERPNext v16.36.1). `test` copies the working tree in first.
- `tests/test_tree.py` also runs without a bench: `python3 -m unittest scope_of_work.tests.test_tree`.
- `tests/test_scope.py` runs on the ERPNext test DB; it rebuilds its catalogue items in `setUpClass`.
- Lint: `uvx ruff@0.17.5 check . && uvx ruff@0.17.5 format --check .`
