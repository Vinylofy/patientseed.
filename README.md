# Public collector development

Credential-free adapter contracts, bounded public collection helpers and immutable
release/data package builders. The manual public queue currently contains 23
domains with provisional platform assignments.

Run local fixture tests:

```bash
python -m unittest discover -s tests -v
```

The `Manual bounded collector cycle` Action starts only through `workflow_dispatch`.
Enter a batch limit from 1 to 100; the Action reads its next position from
`collector-progress/progress.json`, processes at most that many domains, uploads
`collector-run.json`, and advances the cursor after artifact upload. The first
run starts at index 0. A changed queue digest blocks automatic continuation until
the cursor is deliberately migrated. Once index 23 is reached, extend the
reviewed public-domain queue before another run.

Only assigned Shopify domains receive a one-page, 20-product maximum source
sample. WooCommerce, Squarespace and BigCommerce assignments need verified
shop-specific catalog routes and are marked `SOURCE_PROFILE_NEEDED`. A
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

Collection may start only after an explicitly supplied candidate workbook and a
privately approved release. No candidates are discovered, downloaded or synthesized
by these tools. Environment-name checks are a guard, not a substitute for disposable
runner isolation and minimal workflow permissions.
