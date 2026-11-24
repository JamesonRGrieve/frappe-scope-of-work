# Scope of Work

A Frappe app for ERPNext v16 that writes a client's scope of work as a tech tree: small, separately priced
items, each unlocked by the items it requires, laid out left to right from a single root. The client opts
into what it wants now; everything else stays on the tree for later.

The catalogue is your own billable ERPNext Items. A **Scope of Work** copies items from it for one client,
marks what the client asked for and what you recommend, and produces:

- the scope document (Markdown) and the drawn tree (SVG), with requests and recommendations highlighted;
- a draft Quotation, one line per opted-in item named by its ID, with a choice group's other options as
  alternative lines (left out of the total by ERPNext);
- for a Customer, a draft Contract linked to that Quotation, with one fulfilment line per item.

Nothing is submitted. The app ships no catalogue: item wording, prices and client data stay in your ERP.

## The catalogue

- **Branches are Item Groups.** Give each one a branch letter (one capital, not X), a colour and an order
  under *Scope of Work branch* on the Item Group.
- **Items are Items.** Tick *In the scope catalogue* on the Item's *Scope of Work* tab, list what it
  requires (ticked rows are alternatives: one of them is enough), and write what it delivers (one point per
  line), its acceptance, any note and what the client provides.
- **Every item names a proposed stack component** (ERPNext, WordPress, Proxmox, OPNsense…), picked from
  *Scope Stack Component*. It shows in the item's box on the drawing, in the document and on the quote line;
  a scope with an item lacking one is refused.
- **Choice groups** (exactly one option is taken, such as own server or hosting as a service) are an Item
  with *Choice group* ticked; each option is an Item with *Option of* set to it. Other items require the
  group, never an option.
- **Later items** are on the tree but unpriced. **Required** items are on every scope.
- **Prices** are Item Prices on a selling price list. An item without one prints `TBS`.

## A client's scope

1. New **Scope of Work**: the client (Customer, Lead or Prospect), company and price list.
2. *Items → Add Client Requests*, *Add Recommendations* or *Add from Catalogue*. Each item comes with
   everything it requires and gets the next free ID in its branch (`W4`; a group's options `H1a`, `H1b`;
   later items `X1`). Edit the wording per client in the row.
3. Mark the default option of each required choice group. *Opt In Requests and Recommendations* ticks them
   and their prerequisites. Saving refuses a broken tree and says what is wrong.
4. *Documents → Download* or *Attach* the document and drawing; *Make Draft Quotation and Contract*.
5. Set the status to *Sent* when it goes to the client. From then on IDs are fixed: rows can be added or
   withdrawn, never renumbered or removed.

## More

- **Internal estimate.** Hours and internal cost per catalogue item (copied to the scope, editable). The scope
  shows each row's margin, totals for what it charges now, and a red banner for anything priced below cost.
  None of it is ever printed for the client.
- **Packages and suggestions.** A *Scope Package* adds a saved bundle in one go (some items as
  recommendations). An Item's *Often taken with* list is offered after adding items, to add as
  recommendations.
- **Revisions.** Setting the status to *Sent* (or *Record Revision*) keeps the scope as sent. The document
  then carries its revision number and, from revision 2, a *Changes since revision N* section.
- **PDF.** The *Scope of Work* print format and *Download PDF*: the drawing, then the document. The PDF is
  also attached beside the Markdown and SVG.
- **Client page.** *Client → Share with Client* makes a private link (`/scope?key=…`). The client sees the
  tree, ticks items (prerequisites tick and untick themselves, choice groups are radio buttons), watches the
  total, and saves; their ticks become *Opted in*. Locked once Accepted; a new link or *Revoke* closes the old one.
- **Nextcloud and Deck.** *File to Nextcloud and Deck* writes the three files into the client's folder,
  checks each stored size, and attaches each to the scope's Deck card once. Set the address, user and app
  password in *Scope of Work Settings*.
- **Delivery.** Once *Accepted*: *Make Project* (one Task per accepted item, Task dependencies from the
  prerequisites, the stack component as a tag) and *Make Subscription* (the per-month items as monthly
  Subscription Plans for a Customer; invoices stay drafts).

## Development

```sh
tools/test-bench.sh up      # a throwaway ERPNext v16 bench in podman, app installed
tools/test-bench.sh test    # copy the working tree in and run the suite
BENCH_PORT=8137 tools/test-bench.sh up && tools/test-bench.sh serve   # the desk in a browser
tools/test-bench.sh down
python3 -m unittest scope_of_work.tests.test_tree   # the tree alone, no bench
```

## Licence

AGPL-3.0-or-later. Copyright Zephyrex Technologies Limited.
