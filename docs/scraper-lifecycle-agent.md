# Scraper Lifecycle Agent

The public collector processes one queue shop at a time. A manual cycle records source evidence, runs a bounded listing/detail pilot, and builds a scraper wrapper only when the adapter and detail gate pass.

- `collector/scraper-lifecycle.json` is the durable central state file.
- `collector/scraper-lifecycle.md` is the human-readable status view.
- `collector/frozen/<domain>/status.json` records shops after three unsuccessful build attempts.
- `collector/generated/` is published to the private-free `scraper-builds` branch after a successful build.
- `scraper-price-refresh.yml` and `scraper-ean-refresh.yml` collect artifacts only; they never write Supabase or any database.

The price workflow runs every two days. The EAN workflow is limited to 250 detail records per day. A later private importer can review these artifacts and perform any database synchronization separately.
