"""Bounded, evidence-first platform reconnaissance and source pilot."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from collector.adapters.squarespace_new_vinyl import SquarespaceNewVinylAdapter
from collector.adapters.bigcommerce_new_vinyl import BigCommerceNewVinylAdapter
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.transport import Transport, public_source

LIMITS = Limits(max_pages=1, max_requests=12, max_products=20, timeout_seconds=10,
                max_runtime_seconds=60, delay_seconds=0.5)


ADAPTERS = {
    "shopify": ShopifyNewVinylAdapter,
    "woocommerce": WooCommerceNewVinylAdapter,
    "squarespace": SquarespaceNewVinylAdapter,
    "bigcommerce": BigCommerceNewVinylAdapter,
}


def route_candidates(domain: str, hinted_platform: str) -> list[tuple[str, str]]:
    """Return bounded public routes in platform-priority order.

    These are discovery candidates, not a claim that the platform supports the
    route.  The route is only selected after its adapter parses the response.
    """
    groups = {
        "shopify": [
            f"https://{domain}/products.json?limit=20&page=1",
            f"https://{domain}/collections/all/products.json?limit=20&page=1",
        ],
        "woocommerce": [
            f"https://{domain}/wp-json/wc/store/v1/products?per_page=20&page=1",
        ],
        "squarespace": [
            f"https://{domain}/api/0.1/collections/products?format=json",
            f"https://{domain}/api/0.1/collections/all/products?format=json",
        ],
        "bigcommerce": [
            f"https://{domain}/api/storefront/products?limit=20&offset=0",
            f"https://{domain}/api/storefront/products?limit=20",
        ],
    }
    order = [hinted_platform] if hinted_platform in groups else []
    order += [platform for platform in groups if platform not in order]
    return [(platform, route) for platform in order for route in groups[platform]]


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
                   products_seen: int, transport, method_candidates: list[dict] | None = None) -> dict:
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
    if method_candidates:
        result["method_candidates"] = method_candidates
        result["selected_method"] = {
            "platform": platform,
            "route": route,
            "score": max(candidate["score"] for candidate in method_candidates
                          if candidate.get("route") == route),
            "selection": "highest_bounded_adapter_score",
        }
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
    # The wrapper is generated only by build_scrapers after this result is
    # persisted; reconnaissance itself never claims a durable scraper build.
    if checked:
        result["status"] = "ADAPTER_TESTED"
        result["gate"] = "build"
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
    hinted_platform = platform_hint(html)
    candidates = []
    bodies = {}
    for candidate_platform, route in route_candidates(domain, hinted_platform):
        try:
            body = transport.get(route)
            adapter = ADAPTERS[candidate_platform](domain)
            page = adapter.parse_listing(body, source_url=route,
                                         observed_at=datetime.now(timezone.utc).isoformat())
            bodies[route] = body
            accepted = [listing for listing in page.listings
                        if listing.get("product_type") == "vinyl" and listing.get("condition") == "new"]
            candidates.append({
                "platform": candidate_platform,
                "route": route,
                "score": len(accepted) * 10 + (5 if page.listings else 0),
                "products_seen": len(page.listings) + len(page.exclusions),
                "accepted": len(accepted),
                "excluded": len(page.exclusions),
                "status": "ADAPTER_PARSED",
            })
        except (CollectionBlocked, OSError, TimeoutError, ValueError, TypeError, KeyError) as exc:
            candidates.append({
                "platform": candidate_platform,
                "route": route,
                "score": 0,
                "status": "ROUTE_REJECTED",
                "reason": str(exc)[:100] if isinstance(exc, CollectionBlocked) else type(exc).__name__,
            })
    valid = [candidate for candidate in candidates if candidate["status"] == "ADAPTER_PARSED"]
    if not valid:
        reason = "no public catalog route passed an adapter contract"
        if candidates and all(candidate.get("reason") == "Request budget exhausted" for candidate in candidates):
            reason = "discovery request budget exhausted"
        return {**identity, "status": "ROUTE_REVIEW", "gate": "catalog_route",
                "platform": hinted_platform, "reason": reason,
                "method_candidates": candidates}
    selected = max(valid, key=lambda candidate: (candidate["score"], candidate["accepted"],
                                                  candidate["products_seen"]))
    body = bodies[selected["route"]]
    return sample_listing(identity, ADAPTERS[selected["platform"]](domain), body,
                          selected["route"], selected["platform"], selected["products_seen"],
                          transport, candidates)
