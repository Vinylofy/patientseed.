"""Generated scraper profile for deafmanvinyl.com; adapter contract tested by a manual Action run."""
from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from dataclasses import replace
from collector.artist_title import ArtistTitleAdapter

DOMAIN = 'deafmanvinyl.com'
CATALOG_ROUTE = 'https://deafmanvinyl.com/collections/all/products.json?limit=20&page=1'
CURRENCY = 'USD'

class GeneratedDeafmanvinylComScraper:
    domain = DOMAIN
    catalog_route = CATALOG_ROUTE
    adapter_class = ShopifyNewVinylAdapter

    def __init__(self):
        self.adapter = ArtistTitleAdapter(ShopifyNewVinylAdapter(DOMAIN), 'shopify')

    def parse_listing(self, body, *, source_url=None, observed_at):
        page = self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)
        return replace(page, listings=tuple({**item, 'currency': CURRENCY} for item in page.listings)) if CURRENCY else page

    def parse_detail(self, body, *, source_url, listing):
        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)
