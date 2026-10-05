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
Enter a batch limit from 1 to 100; the Action reads its next position from
`collector-progress/progress.json`, processes at most that many domains, uploads
`collector-run.json`, and advances the cursor after artifact upload. Its
`collector-progress` branch keeps per-row outcomes as durable queue progress.
The first run starts at index 0. Future workbook additions may be appended;
editing or reordering an existing queue prefix stops the cursor for review.

To regenerate the queue after reviewing a new workbook, install `openpyxl` in the
development environment and run `python -m collector.build_queue --workbook
"data/Vinylofy_gecombineerde_shops (5).xlsx" --bootstrap
collector/bootstrap-domains.json --output collector/public-queue.json`. The
current generator checks the known 3,303-row section; adjust its row bounds and
review the resulting diff when the workbook structure changes.

Only assigned Shopify domains receive a one-page, 20-product maximum source
sample. WooCommerce, Squarespace and BigCommerce assignments need verified
shop-specific catalog routes and are marked `SOURCE_PROFILE_NEEDED`. A
missing URL, shared platform or repeated domain is marked `SOURCE_REVIEW`.
Unassigned valid domains stay `SOURCE_PROFILE_NEEDED`, so their adapters remain
open development work. A
`LISTING_SAMPLE` proves only the bounded listing observation; it does not prove
detail/EAN coverage, a complete catalog, market prices, or a production-ready
scraper. The Action does not generate adapter code or import into Vinylofy.
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
