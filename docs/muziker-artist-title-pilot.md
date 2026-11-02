# Muziker artist/title pilot

Status: `SCRAPER_BUILT_TESTED` (public collector; no database writes)

- Source: `https://www.muziker.nl/vinyl-lps-en-cds`
- Catalog route: `https://www.muziker.nl/vinyl-lps`
- Domain: `muziker.nl`
- Adapter: `collector.adapters.muziker.MuzikerAdapter`
- Identity: explicit artist/title from the public product tile
- Price: EUR listing price, taken from the product tile
- Availability: public stock label (`Op voorraad` is treated as in stock)
- EAN: not inferred and not required; the detail parser preserves artist/title
  and returns no identifier because the source does not expose a reliable EAN
  contract.
- Pagination: follows the public `load-next-products`/next-page link.

A live page-1 HTML sample produced 34 artist/title/price records. This is a
bounded route/parser proof, not a claim that the complete catalog was crawled.
The adapter remains credential-free and must pass the normal Factory quality
gate before any private deployment or database import.
