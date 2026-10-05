"""One-page, credential-free source reconnaissance for a public domain queue."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from collector.adapters.catalog import adapter_for
from collector.adapters.shopify_new_vinyl import ShopifyNewVinylAdapter
from collector.collection import collect
from collector.contracts import CollectionBlocked, Limits
from collector.transport import Transport


def queue_digest(queue: list[dict]) -> str:
    return hashlib.sha256(json.dumps(queue, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load_queue(path: Path) -> list[dict]:
    queue = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(queue, list) or not queue:
        raise ValueError("queue must be a nonempty shop array")
    for item in queue:
        if (not isinstance(item, dict) or set(item) != {"row", "name", "domain", "source_status"}
                or type(item["row"]) is not int or item["row"] < 1
                or not isinstance(item["name"], str) or not item["name"]
                or not isinstance(item["domain"], str)
                or item["source_status"] not in {"READY", "MISSING_SOURCE", "INVALID_SOURCE",
                                                 "SHARED_PLATFORM", "DUPLICATE_DOMAIN"}):
            raise ValueError("invalid shop queue item")
    if len({item["row"] for item in queue}) != len(queue):
        raise ValueError("duplicate workbook row in queue")
    return queue


def run(queue: list[dict], start_index: int, batch_limit: int, *, transport_factory=Transport) -> dict:
    if not 0 <= start_index <= len(queue) or not 1 <= batch_limit <= 100:
        raise ValueError("invalid start index or batch limit")
    results = []
    limits = Limits(max_pages=1, max_requests=1, max_products=20, max_runtime_seconds=30)
    for item in queue[start_index:start_index + batch_limit]:
        domain = item["domain"]
        identity = {"row": item["row"], "name": item["name"], "domain": domain}
        if item["source_status"] != "READY":
            results.append({**identity, "status": "SOURCE_REVIEW", "reason": item["source_status"]})
            continue
        adapter = adapter_for(domain)
        if adapter is None:
            results.append({**identity, "status": "SOURCE_PROFILE_NEEDED", "reason": "no assigned adapter"})
        elif not isinstance(adapter, ShopifyNewVinylAdapter):
            # These platform scaffolds do not yet have proven shop-specific catalog routes.
            results.append({**identity, "status": "SOURCE_PROFILE_NEEDED", "reason": "catalog route unverified"})
        else:
            url = f"https://{domain}/products.json?limit=20&page=1"
            try:
                sample = collect(adapter, transport_factory(domain, limits), url, limits)
                results.append({**identity, "status": "LISTING_SAMPLE" if sample["listings"] else "SOURCE_REVIEW",
                                "accepted": len(sample["listings"]), "excluded": len(sample["exclusions"]),
                                "source_url": url, "pagination_complete": sample["pagination"]["complete"]})
            except (CollectionBlocked, ValueError, OSError, TimeoutError) as exc:
                # A failed shop does not stop the next one. Do not publish page bodies or credentials.
                results.append({**identity, "status": "SOURCE_BLOCKED", "reason": type(exc).__name__,
                                "detail": str(exc)[:120] if isinstance(exc, CollectionBlocked) else "source response invalid"})
    return {"schema_version": 1, "queue_sha256": queue_digest(queue), "start_index": start_index,
            "batch_limit": batch_limit, "processed": len(results), "next_start_index": start_index + len(results),
            "queue_size": len(queue), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--batch-limit", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(load_queue(args.queue), args.start_index, args.batch_limit)
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Processed {result['processed']} of {result['queue_size']}; next index {result['next_start_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
