# Public collector development

Credential-free adapter contracts, bounded public collection helpers and immutable
release/data package builders. The user-supplied workbook is preserved at
`data/Vinylofy_gecombineerde_shops (5).xlsx`. The derived public queue contains
one work item for each of its 3,303 shop rows. The previously reviewed 23 domains
remain first; the other rows follow workbook order.
The workbook SHA-256 is
`9a013f48e1ccbf83c9c849528f38df7c3704a5f7eadb7db868f1f330ac6e854f`.

Run local fixture tests:

```bash
python -m unittest discover -s tests -v
```

The `Manual bounded collector cycle` Action starts only through `workflow_dispatch`.
Enter a positive batch limit up to the remaining queue; the Action reads its next position from
`collector-progress/progress.json`, processes at most that many shop rows with
four domain workers, uploads `collector-run.json`, and advances the cursor after
artifact upload. Its `collector-progress` branch keeps per-row evidence as the
durable central progress record. Each successful run also renders one full
`scraper-status.md` snapshot for all 3,303 rows as an artifact. A local partial
result is uploaded if a run fails; only a complete result advances the cursor.
The first run starts at index 0. Future workbook additions may be appended;
editing or reordering an existing queue prefix stops the cursor for review.
Set `reset_cursor` to `true` only when you deliberately want to start again at
the first Excel row. Leave it `false` for normal continuation.

To regenerate the queue after reviewing a new workbook, install `openpyxl` in the
development environment and run `python -m collector.build_queue --workbook
"data/Vinylofy_gecombineerde_shops (5).xlsx" --bootstrap
collector/bootstrap-domains.json --output collector/public-queue.json`. The
current generator checks the known 3,303-row section; adjust its row bounds and
review the resulting diff when the workbook structure changes.

For valid domains, the worker reads at most one homepage and one platform route.
Shopify product feeds receive a one-page, 20-product maximum listing sample
and up to two product-detail requests. A successful detail probe first produces
`ADAPTER_TESTED`; the Action then generates a shop-specific wrapper and JSON
profile under `collector/generated/`, imports the wrapper as a self-test, and
publishes both files to the durable `scraper-builds` branch. Only after that
step does the row become `SCRAPER_BUILT_TESTED`. A route that parses but has no
confirmed new vinyl becomes `ADAPTER_TESTED` and stays open at the listing gate.
WooCommerce Store API routes are checked for a product array and, when explicit
new/vinyl/price/stock fields are present, use the same adapter-and-detail path.
The Rockin' Out Records pilot is an explicit HTML-category adapter: it follows
the category `rel=next` pagination, keeps listing EAN empty, and reads EAN/GTIN
only from product-detail JSON-LD.
Squarespace and BigCommerce are fingerprinted, with catalog-route work left
open. Unknown sites get one bounded Shopify-feed probe, then remain open for
platform research when its contract is absent. Missing URLs, shared platforms
and repeated domains are marked `SOURCE_REVIEW`. A built scraper is still not
market-approved or production-ready: GTIN counts use checksum checks on tiny
samples and private QA, market pricing and imports remain separate gates. The
Action does not generate custom shop code or import into Vinylofy.
There is no schedule, private runner, database endpoint, model credential or
production import.

Adapters implement `collector.contracts.Adapter.parse_listing` and return raw public
listing observations. New vinyl only; unknown or used condition is excluded. Listing
price and availability remain authoritative during bounded detail enrichment.
EAN/UPC matching and private acceptance are performed exclusively by the private
validator. Public artifacts retain identifiers exactly as observed.

`collector.packages.release_package` reads only explicitly allowlisted files from
an exact committed Git SHA. `data_package` creates a separate observation package
with that release's commit/digest and complete run provenance. Private jobs pull
and independently validate both; this repository never calls a private endpoint.
Package construction is not release approval. No release is published automatically.

Collection may start only after the explicitly supplied candidate workbook and a
privately approved release. The queue is derived from that exact workbook; no
candidates are discovered, downloaded or synthesized from external websites.
Environment-name checks are a guard, not a substitute for disposable runner
isolation and minimal workflow permissions.
