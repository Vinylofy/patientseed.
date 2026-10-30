"""Generated scraper profile for biglovevinyl.com; adapter contract tested by a manual Action run."""
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter

DOMAIN = 'biglovevinyl.com'
CATALOG_ROUTE = 'https://biglovevinyl.com/wp-json/wc/store/v1/products?per_page=20&page=1'

class GeneratedBiglovevinylComScraper:
    domain = DOMAIN
    catalog_route = CATALOG_ROUTE
    adapter_class = WooCommerceNewVinylAdapter

    def __init__(self):
        self.adapter = WooCommerceNewVinylAdapter(DOMAIN)

    def parse_listing(self, body, *, source_url=None, observed_at):
        return self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)

    def parse_detail(self, body, *, source_url, listing):
        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)
