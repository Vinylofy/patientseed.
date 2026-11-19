"""Generated scraper profile for sensationrecords.com; adapter contract tested by a manual Action run."""
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from dataclasses import replace

DOMAIN = 'sensationrecords.com'
CATALOG_ROUTE = 'https://sensationrecords.com/wp-json/wc/store/v1/products?per_page=20&page=1'
CURRENCY = None

class GeneratedSensationrecordsComScraper:
    domain = DOMAIN
    catalog_route = CATALOG_ROUTE
    adapter_class = WooCommerceNewVinylAdapter

    def __init__(self):
        self.adapter = WooCommerceNewVinylAdapter(DOMAIN)

    def parse_listing(self, body, *, source_url=None, observed_at):
        page = self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)
        return replace(page, listings=tuple({**item, 'currency': CURRENCY} for item in page.listings)) if CURRENCY else page

    def parse_detail(self, body, *, source_url, listing):
        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)
