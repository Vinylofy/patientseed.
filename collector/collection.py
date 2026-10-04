from __future__ import annotations

from datetime import datetime, timezone

from collector.contracts import Adapter, CollectionBlocked, Limits, assert_credential_free_environment
from collector.transport import Transport, public_source


def collect(adapter: Adapter, transport: Transport, first_url: str, limits: Limits) -> dict:
    assert_credential_free_environment()
    url, visited, products, exclusions = first_url, set(), {}, []
    stop_reason = "page_budget"
    for _ in range(limits.max_pages):
        public_source(url, transport.domain)
        if url in visited:
            stop_reason = "repeated_page"
            break
        visited.add(url)
        body = transport.get(url)
        page = adapter.parse_listing(body, source_url=url, observed_at=datetime.now(timezone.utc).isoformat())
        new = 0
        for row in page.listings:
            if row.get("product_type") != "vinyl" or row.get("condition") != "new":
                exclusions.append({"url": public_source(row["url"], transport.domain),
                                   "signal": "not_confirmed_new_vinyl", "at": row.get("observed_at")})
                continue
            public_source(row["url"], transport.domain)
            if row.get("price_source") != "listing" or row.get("availability_source") != "listing":
                raise CollectionBlocked("Listing authority required")
            existing = products.get(row["url"])
            if existing is None:
                new += 1
            # A price-less duplicate cannot replace a price-bearing listing payload.
            if existing is None or row.get("price"):
                products[row["url"]] = row
            if len(products) >= limits.max_products:
                stop_reason = "product_budget"
                break
        exclusions.extend({key: item.get(key) for key in ("url", "signal", "at")} for item in page.exclusions)
        if stop_reason == "product_budget":
            break
        if not page.listings and page.next_url is None:
            stop_reason = "empty_page"
            break
        if page.listings and not new:
            stop_reason = "no_new_products"
            break
        if page.next_url is None:
            stop_reason = "explicit_end"
            break
        url = page.next_url
    return {"listings": list(products.values()), "exclusions": exclusions,
            "pagination": {"pages": len(visited), "unique_links": len(products), "stop_reason": stop_reason,
                           "complete": stop_reason in {"explicit_end", "empty_page"}}}
