# Public candidate sources

`findyl-online-2026-10-25.csv` contains the 50 direct shop/platform URLs extracted
from https://findyl.co.uk/online-stores on 25 October 2026. Affiliate wrappers
and tracking parameters were removed. The adjacent JSON manifest records the
source HTML checksum, source URLs, prior row references and queue IDs.

All 50 entries are appended after the unchanged 3,303 original workbook rows.
IDs 3310–3359 are synthetic source IDs, not extra rows in the original workbook.
Rough Trade, Resident Music and Assai are explicit rechecks of existing domains;
Discogs already appeared and remains a shared-platform review. Amazon UK and
eBay UK are also shared platforms: no generic shop scraper is built for them.
The original workbook and durable history/recheck evidence are preserved.

Use the ordinary discovery/build Action with batch_limit=50 and reset_cursor=false.
The cursor begins at the first appended candidate; it must never be reset for an
additional source. Built profiles enter the existing quality gate. To prioritize
this source, use source_list=findyl-online-2026-10-25 in Quality admission and
repair (maximum 25 per run); both source groups share the same durable QA state.
`scraper-status.md` remains the single human-readable progress document.

Storefront currency is copied only from explicit public Shopify.currency.active
metadata into that shop's generated wrapper/profile. It is not inferred from
country. Quality admission still requires independent matching product/variant
price and currency evidence. The shared US adapter and other published wrappers
are unchanged. Unknown/custom platforms remain in route review; missing public
EAN/price evidence does not count as admission. No database writes occur.
