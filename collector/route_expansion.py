"""Discover alternate public catalog routes, then run the bounded detail gate."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.adapters.woocommerce_new_vinyl import WooCommerceNewVinylAdapter
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.detail_recheck import recheck
from collector.manual_run import load_queue, queue_digest
from collector.transport import Transport


def route_candidates(domain: str, prior_platform: str | None) -> list[tuple[str, str]]:
    shopify = [
        ("shopify", f"https://{domain}/products.json?limit=20&page=1"),
        ("shopify", f"https://{domain}/collections/all/products.json?limit=20&page=1"),
    ]
    woocommerce = [
        ("woocommerce", f"https://{domain}/wp-json/wc/store/v1/products?per_page=20&page=1"),
    ]
    if prior_platform == "shopify":
        return shopify + woocommerce
    if prior_platform == "woocommerce":
        return woocommerce + shopify
    return shopify + woocommerce


def discover(item: dict, prior: dict, transport_factory=Transport) -> tuple[str, str] | None:
    limits = Limits(max_pages=1, max_requests=6, max_products=20, timeout_seconds=10,
                    max_runtime_seconds=60, delay_seconds=0.5)
    transport = transport_factory(item["domain"], limits)
    for platform, route in route_candidates(item["domain"], prior.get("platform")):
        try:
            body = transport.get(route)
            payload = json.loads(body)
            if platform == "shopify" and isinstance(payload, dict) and isinstance(payload.get("products"), list):
                return platform, route
            if platform == "woocommerce" and isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
                return platform, route
        except (CollectionBlocked, OSError, TimeoutError, ValueError, TypeError):
            continue
    return None


def run(queue: list[dict], state: dict, *, candidate_limit: int, catalog_pages: int,
        detail_samples: int, transport_factory=Transport) -> dict:
    history = {item["row"]: item for item in state.get("history", [])}
    for item in state.get("rechecks", []):
        history[item["row"]] = item
    selected = []
    for item in queue:
        prior = history.get(item["row"], {})
        if prior.get("status") in {"DETAIL_GATE_BLOCKED", "ROUTE_REVIEW", "PLATFORM_IDENTIFIED", "ADAPTER_TESTED"}:
            selected.append((item, prior))
    results = []
    for item, prior in selected[:candidate_limit]:
        found = discover(item, prior, transport_factory)
        if found is None:
            results.append({"row": item["row"], "name": item["name"], "domain": item["domain"],
                            "status": "DETAIL_GATE_BLOCKED", "gate": "catalog_route",
                            "platform": prior.get("platform"),
                            "reason": "alternate public catalog route not proven"})
            continue
        platform, route = found
        enriched = {**prior, "platform": platform, "source_url": route}
        results.append(recheck(item, enriched, catalog_pages=catalog_pages,
                               detail_samples=detail_samples, transport_factory=transport_factory))
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.candidate_limit or not 1 <= args.catalog_pages <= 5 or not 1 <= args.detail_samples <= 3:
        parser.error("candidate-limit must be positive; catalog-pages 1..5; detail-samples 1..3")
    assert_credential_free_environment()
    result = run(load_queue(args.queue), json.loads(args.progress.read_text(encoding="utf-8")),
                 candidate_limit=args.candidate_limit, catalog_pages=args.catalog_pages,
                 detail_samples=args.detail_samples)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Discovered routes and rechecked {result['processed']} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
