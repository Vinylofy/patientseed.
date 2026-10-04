# Public collector development

Credential-free adapter contracts, bounded public collection helpers and immutable
release/data package builders. This repository contains no shop adapter yet and
does not start a pilot or queue.

Run local fixture tests:

```bash
python -m unittest discover -s tests -v
```

The manual validation workflow runs only tests. No schedule, private runner,
database endpoint, model credential or production import is configured.

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
