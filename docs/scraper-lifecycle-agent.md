# Scraper Lifecycle Agent

The public collector processes one queue shop at a time. A manual cycle records source evidence, probes the bounded set of public catalog methods, ranks the routes that an adapter can actually parse, and uses the best proven route for the listing/detail pilot. A scraper wrapper is built only when that selected adapter and the detail gate pass.

Discovery is evidence-based rather than platform-name based. The run artifact records every tested route in `method_candidates` and the selected route in `selected_method`; the generated scraper profile carries both fields forward. A rejected route or an unknown platform remains a review/blocker and is never silently converted into a scraper.

- `collector/scraper-lifecycle.json` is the durable central state file.
- `collector/scraper-lifecycle.md` is the human-readable status view.
- `collector/frozen/<domain>/status.json` records shops after three unsuccessful build attempts.
- `collector/generated/` is published to the private-free `scraper-builds` branch after a successful build.
- `scraper-price-refresh.yml` and `scraper-ean-refresh.yml` collect artifacts only; they never write Supabase or any database.

The price workflow runs every two days. The EAN workflow is limited to 250 detail records per day. A later private importer can review these artifacts and perform any database synchronization separately.

The public discovery cycle is scheduled ten times per UTC day at two-hour intervals, with a batch size of 100. It advances the durable queue cursor and uses a concurrency lock so batches do not overlap. A manual dispatch remains available for recovery or a deliberate restart.
