"""Generated scraper profile for firetalk.shop; adapter contract tested by a manual Action run."""
from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter

DOMAIN = 'firetalk.shop'
CATALOG_ROUTE = 'https://firetalk.shop/products.json?limit=20&page=1'

class GeneratedFiretalkShopScraper:
    domain = DOMAIN
    catalog_route = CATALOG_ROUTE
    adapter_class = ShopifyNewVinylAdapter

    def __init__(self):
        self.adapter = ShopifyNewVinylAdapter(DOMAIN)

    def parse_listing(self, body, *, source_url=None, observed_at):
        return self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)

    def parse_detail(self, body, *, source_url, listing):
        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)
