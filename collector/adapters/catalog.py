"""Public, credential-free adapter assignments for the first shop set."""
from __future__ import annotations

from collector.adapters.bigcommerce_new_vinyl import BigCommerceNewVinylAdapter
from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.squarespace_new_vinyl import SquarespaceNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter


SHOP_ADAPTERS = {
    "1234gorecords.shop": ShopifyNewVinylAdapter,
    "10000hzrecords.com": ShopifyNewVinylAdapter,
    "606records.com": ShopifyNewVinylAdapter,
    "alldayrecords.com": ShopifyNewVinylAdapter,
    "allthebestflorence.com": ShopifyNewVinylAdapter,
    "antonesrecordshop.com": ShopifyNewVinylAdapter,
    "apolloexos.com": ShopifyNewVinylAdapter,
    "abrodosmusic.com": ShopifyNewVinylAdapter,
    "afkbooksandrecords.com": ShopifyNewVinylAdapter,
    "alliedrecordexchange.com": ShopifyNewVinylAdapter,
    "a2vintageypsi.com": ShopifyNewVinylAdapter,
    "twoshopsinorange.com": ShopifyNewVinylAdapter,
    "14arecords.com": WooCommerceNewVinylAdapter,
    "74kid.com": WooCommerceNewVinylAdapter,
    "analogarchivers.com": WooCommerceNewVinylAdapter,
    "anaphoradiscs.com": WooCommerceNewVinylAdapter,
    "11thstreetrecords.net": SquarespaceNewVinylAdapter,
    "rpmunderground.us": SquarespaceNewVinylAdapter,
    "adayintheliferecords.com": SquarespaceNewVinylAdapter,
    "a-1recordshop.com": SquarespaceNewVinylAdapter,
    "amcollectivehuntsville.com": SquarespaceNewVinylAdapter,
    "apparitionsvintage.com": SquarespaceNewVinylAdapter,
    "almostanythingopelika.com": BigCommerceNewVinylAdapter,
}


def adapter_for(domain: str):
    """Return a configured public adapter, or None when route evidence is absent."""
    adapter = SHOP_ADAPTERS.get(domain.lower().removeprefix("www."))
    return adapter(domain) if adapter else None
