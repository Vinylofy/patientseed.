"""Recheck previously identified public shops with bounded catalog depth."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from collector.adapters.squarespace_new_vinyl import SquarespaceNewVinylAdapter
from collector.adapters.bigcommerce_new_vinyl import BigCommerceNewVinylAdapter
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.manual_run import load_queue, queue_digest
from collector.recon import valid_gtin
from collector.transport import Transport, public_source


ELIGIBLE = {"ADAPTER_TESTED", "ROUTE_REVIEW", "PLATFORM_IDENTIFIED"}


def page_url(route: str, page: int) -> str:
    parsed = urlsplit(route)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))


def recheck(item: dict, prior: dict, *, catalog_pages: int, detail_samples: int,
            transport_factory=Transport) -> dict:
    identity = {"row": item["row"], "name": item["name"], "domain": item["domain"]}
    platform = prior.get("platform")
    route = prior.get("source_url")
    if platform not in {"shopify", "woocommerce", "squarespace", "bigcommerce"} or not isinstance(route, str):
        return {**identity, "status": "DETAIL_GATE_BLOCKED", "gate": "catalog_route",
                "platform": platform, "reason": "supported public catalog route not proven"}
    assert_credential_free_environment()
    limits = Limits(max_pages=catalog_pages, max_requests=catalog_pages + detail_samples + 2,
                    max_products=20, timeout_seconds=10, max_runtime_seconds=120, delay_seconds=0.5)
    transport = transport_factory(item["domain"], limits)
    adapter = {"shopify": ShopifyNewVinylAdapter, "woocommerce": WooCommerceNewVinylAdapter,
               "squarespace": SquarespaceNewVinylAdapter, "bigcommerce": BigCommerceNewVinylAdapter}[platform](item["domain"])
    listings, exclusions, products_seen = [], [], 0
    try:
        for number in range(1, catalog_pages + 1):
            current = page_url(route, number)
            body = transport.get(current)
            parsed = adapter.parse_listing(body, source_url=current, observed_at=datetime.now(timezone.utc).isoformat())
            products_seen += len(parsed.listings) + len(parsed.exclusions)
            exclusions.extend(parsed.exclusions)
            listings.extend(parsed.listings)
            if not parsed.listings and not parsed.exclusions:
                break
    except (CollectionBlocked, OSError, TimeoutError, ValueError, TypeError, KeyError) as exc:
        return {**identity, "status": "DETAIL_GATE_BLOCKED", "gate": "catalog_route", "platform": platform,
                "source_url": route, "reason": type(exc).__name__, "catalog_pages_checked": len(listings)}
    unique = []
    seen = set()
    for listing in listings:
        key = listing.get("url")
        if isinstance(key, str) and key not in seen:
            seen.add(key); unique.append(listing)
    checked = valid = 0
    detail_reason = None
    for listing in unique[:detail_samples]:
        try:
            detail = adapter.parse_detail(transport.get(listing["url"].split("?", 1)[0]),
                                          source_url=listing["url"].split("?", 1)[0], listing=listing)
        except (CollectionBlocked, OSError, TimeoutError, ValueError) as exc:
            detail_reason = type(exc).__name__
            continue
        checked += 1
        valid += int(valid_gtin(detail.get("identifier_raw")))
    result = {**identity, "status": "ADAPTER_TESTED" if checked else "DETAIL_GATE_BLOCKED",
              "gate": "build" if checked else "detail", "platform": platform, "source_url": route,
              "adapter_status": "REUSED_AND_RETESTED", "products_seen": products_seen,
              "accepted": len(unique), "excluded": len(exclusions), "catalog_pages_checked": catalog_pages,
              "detail_checked": checked, "detail_gtin_valid": valid}
    if detail_reason:
        result["detail_reason"] = detail_reason
    if not checked:
        result["reason"] = "no detail page passed the bounded recheck"
    return result


def run(queue: list[dict], state: dict, *, candidate_limit: int, catalog_pages: int,
        detail_samples: int, retry_blocked: bool, transport_factory=Transport) -> dict:
    history = {item["row"]: item for item in state.get("history", [])}
    candidates = []
    for item in queue:
        prior = history.get(item["row"], {})
        status = prior.get("status")
        if status in ELIGIBLE or (retry_blocked and status in {"SOURCE_BLOCKED", "DETAIL_GATE_BLOCKED"}):
            candidates.append((item, prior))
    selected = candidates[:candidate_limit]
    results = [recheck(item, prior, catalog_pages=catalog_pages, detail_samples=detail_samples,
                       transport_factory=transport_factory) for item, prior in selected]
    return {"schema_version": 1, "queue_sha256": queue_digest(queue), "complete": True,
            "candidate_limit": candidate_limit, "catalog_pages": catalog_pages,
            "detail_samples": detail_samples, "processed": len(results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, required=True)
    parser.add_argument("--catalog-pages", type=int, required=True)
    parser.add_argument("--detail-samples", type=int, required=True)
    parser.add_argument("--retry-blocked", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.candidate_limit or not 1 <= args.catalog_pages <= 5 or not 1 <= args.detail_samples <= 3:
        parser.error("candidate-limit must be positive; catalog-pages 1..5; detail-samples 1..3")
    result = run(load_queue(args.queue), json.loads(args.progress.read_text(encoding="utf-8")),
                 candidate_limit=args.candidate_limit, catalog_pages=args.catalog_pages,
                 detail_samples=args.detail_samples, retry_blocked=args.retry_blocked)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Rechecked {result['processed']} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
