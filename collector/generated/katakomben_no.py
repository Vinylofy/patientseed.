"""Generated scraper profile for katakomben.no; adapter contract tested by a manual Action run."""
from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from dataclasses import replace

DOMAIN = 'katakomben.no'
CATALOG_ROUTE = 'https://katakomben.no/products.json?limit=20&page=1'
CURRENCY = 'NOK'

class GeneratedKatakombenNoScraper:
    domain = DOMAIN
    catalog_route = CATALOG_ROUTE
    adapter_class = ShopifyNewVinylAdapter

    def __init__(self):
        self.adapter = ShopifyNewVinylAdapter(DOMAIN)

    def parse_listing(self, body, *, source_url=None, observed_at):
        page = self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)
        return replace(page, listings=tuple({**item, 'currency': CURRENCY} for item in page.listings)) if CURRENCY else page

    def parse_detail(self, body, *, source_url, listing):
        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)
