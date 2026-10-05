"""Bounded, evidence-first platform reconnaissance and source pilot."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.transport import Transport, public_source

LIMITS = Limits(max_pages=1, max_requests=4, max_products=20, timeout_seconds=10,
                max_runtime_seconds=60, delay_seconds=0.5)


def platform_hint(html: str) -> str:
    text = html[:250_000].lower()
    if any(signal in text for signal in ("cdn.shopify.com", "shopify.theme", "shopify-section")):
        return "shopify"
    if any(signal in text for signal in ("woocommerce", "wp-content/plugins/woocommerce")):
        return "woocommerce"
    if any(signal in text for signal in ("static1.squarespace.com", "squarespace-cdn.com")):
        return "squarespace"
    if "bigcommerce" in text:
        return "bigcommerce"
    return "unknown"


def valid_gtin(value: object) -> bool:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) not in (12, 13, 14):
        return False
    digits = [int(ch) for ch in value]
    total = sum(digit * (3 if offset % 2 else 1) for offset, digit in enumerate(reversed(digits[:-1])))
    return (10 - total % 10) % 10 == digits[-1]


def sample_listing(identity: dict, adapter, body: str, route: str, platform: str,
                   products_seen: int, transport) -> dict:
    try:
        page = adapter.parse_listing(body, source_url=route, observed_at=datetime.now(timezone.utc).isoformat())
        accepted = []
        for listing in page.listings:
            public_source(listing["url"], identity["domain"])
            if listing.get("product_type") == "vinyl" and listing.get("condition") == "new":
                accepted.append(listing)
        accepted = accepted[:LIMITS.max_products]
    except (CollectionBlocked, ValueError, TypeError, KeyError) as exc:
        return {**identity, "status": "CATALOG_ROUTE_VERIFIED", "gate": "listing", "platform": platform,
                "source_url": route, "products_seen": products_seen,
                "reason": "listing contract needs review", "error_type": type(exc).__name__}
    result = {**identity, "status": "ADAPTER_TESTED",
              "gate": "detail" if accepted else "listing", "platform": platform, "source_url": route,
              "adapter_class": type(adapter).__name__, "adapter_status": "REUSED_AND_TESTED",
              "products_seen": products_seen, "accepted": len(accepted),
              "excluded": len(page.exclusions), "pagination_complete": False,
              "listing_gtin_valid": sum(valid_gtin(row.get("identifier_raw")) for row in accepted)}
    if not accepted:
        result["reason"] = "no confirmed new vinyl on bounded page"
        return result
    checked = valid = 0
    seen_paths = set()
    for listing in accepted:
        detail_url = listing["url"].split("?", 1)[0]
        if detail_url in seen_paths:
            continue
        seen_paths.add(detail_url)
        if len(seen_paths) > 2:
            break
        try:
            detail = adapter.parse_detail(transport.get(detail_url), source_url=detail_url, listing=listing)
        except (CollectionBlocked, OSError, TimeoutError, ValueError) as exc:
            result["detail_status"] = "BLOCKED"
            result["detail_reason"] = str(exc)[:100] if isinstance(exc, CollectionBlocked) else type(exc).__name__
            break
        checked += 1
        valid += valid_gtin(detail.get("identifier_raw"))
    result["detail_checked"] = checked
    result["detail_gtin_valid"] = valid
    result.setdefault("detail_status", "SAMPLED")
    if checked:
        result["status"] = "SCRAPER_BUILT_TESTED"
        result["gate"] = "qa"
    return result


def probe(item: dict, transport_factory=Transport) -> dict:
    """At most four same-domain GETs; never infer a complete catalog or market price."""
    identity = {"row": item["row"], "name": item["name"], "domain": item["domain"]}
    if item["source_status"] != "READY":
        return {**identity, "status": "SOURCE_REVIEW", "gate": "identity", "reason": item["source_status"]}
    assert_credential_free_environment()
    domain = item["domain"]
    transport = transport_factory(domain, LIMITS)
    homepage = f"https://{domain}/"
    try:
        html = transport.get(homepage)
    except (CollectionBlocked, OSError, TimeoutError) as exc:
        return {**identity, "status": "SOURCE_BLOCKED", "gate": "identity",
                "reason": str(exc)[:100] if isinstance(exc, CollectionBlocked) else type(exc).__name__,
                "source_url": homepage}
    platform = platform_hint(html)
    if platform in {"squarespace", "bigcommerce"}:
        return {**identity, "status": "PLATFORM_IDENTIFIED", "gate": "catalog_route", "platform": platform,
                "reason": "shop-specific catalog route needed", "source_url": homepage}
    if platform == "woocommerce":
        route = f"https://{domain}/wp-json/wc/store/v1/products?per_page=20&page=1"
        try:
            payload = json.loads(transport.get(route))
        except (CollectionBlocked, OSError, TimeoutError, ValueError) as exc:
            return {**identity, "status": "ROUTE_REVIEW", "gate": "catalog_route", "platform": platform,
                    "reason": str(exc)[:100] if isinstance(exc, CollectionBlocked) else type(exc).__name__,
                    "source_url": route}
        if not isinstance(payload, list) or any(not isinstance(product, dict) for product in payload):
            return {**identity, "status": "ROUTE_REVIEW", "gate": "catalog_route", "platform": platform,
                    "reason": "Store API product array unproven", "source_url": route}
        return sample_listing(identity, WooCommerceNewVinylAdapter(domain), json.dumps(payload),
                              route, platform, len(payload), transport)
    # A single Shopify feed probe also identifies shops whose homepage lacks platform markers.
    route = f"https://{domain}/products.json?limit=20&page=1"
    try:
        body = transport.get(route)
    except (CollectionBlocked, OSError, TimeoutError) as exc:
        return {**identity, "status": "ROUTE_REVIEW" if platform == "shopify" else "PLATFORM_REVIEW",
                "gate": "catalog_route", "platform": platform,
                "reason": str(exc)[:100] if isinstance(exc, CollectionBlocked) else type(exc).__name__,
                "source_url": route}
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or set(payload) != {"products"} or not isinstance(payload["products"], list):
        return {**identity, "status": "ROUTE_REVIEW" if platform == "shopify" else "PLATFORM_REVIEW",
                "gate": "catalog_route", "platform": platform, "reason": "Shopify feed contract unproven",
                "source_url": route}
    return sample_listing(identity, ShopifyNewVinylAdapter(domain), body, route, "shopify",
                          len(payload["products"]), transport)
