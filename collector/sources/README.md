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

## Waxtra album source, 19 November 2026

`waxtra-rumours-2026-11-19.csv` lists all 198 unique shop domains embedded in
https://waxtra.com/album/38722, including collapsed offers. The JSON manifest
records the HTML checksum, 76 existing domains with their queue IDs, and
122 new candidates appended after the unchanged 3353-item queue.
The original workbook and progress are preserved. This is an album-page snapshot,
not an exhaustive Waxtra directory. Platform/country fields are unverified source
hints; used-only shops must still fail the ordinary new-vinyl gate. No collection,
QA approval, scheduling or imports are triggered by adding these candidates.

## LP/EP Finder directory, 19 November 2026

`lpepfinder-shops-2026-11-19.csv` lists all 2196 unique domains found across all
71 country pages linked from https://lpepfinder.com/shops/. Each country page
was checked against its own displayed shop count (2196 total listings).
The JSON manifest records per-page checksums, source links and queue IDs:
578 existing domains are cross-referenced; 1618 new candidates are appended
after the unchanged 3475-item queue. HTTPS root URLs are derived from
the directory domain slugs. Country labels and names are unverified directory
observations. Original workbook, queue prefix and durable progress are preserved.
Normal source/new-vinyl review and QA are still required; this addition triggers
no shop collection, schedules or imports.

## Vinylscout vinyl shops, 19 November 2026

`vinylscout-shops-2026-11-19.csv` lists all 15 vinyl vendors from the public
ItemList at https://vinylscout.nl/winkels. The JSON manifest records the source
checksum, 6 existing-domain references and 9 appended candidates.
The existing 5093-item queue prefix and progress are preserved. Domain
root URLs are derived from displayed vendor domains; store access and new-vinyl
suitability await ordinary review. bol.com is recorded as a shared marketplace.
Hardware-only retailers elsewhere on the site are outside this vinyl list.
No shop collection, QA admission, schedules or imports are triggered.
