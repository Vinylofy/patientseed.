"""Run a credential-free bounded pilot for Rockin' Out Records."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from collector.adapters.rockinoutrecords import RockinOutRecordsAdapter
from collector.collection import collect
from collector.contracts import Limits, assert_credential_free_environment
from collector.transport import Transport


def run(*, pages: int = 3, products: int = 20, detail_samples: int = 2) -> dict:
    assert_credential_free_environment()
    domain = "rockinoutrecords.nl"
    first_url = f"https://{domain}/product-category/vinyl-lp-nieuw/"
    limits = Limits(max_pages=pages, max_requests=pages + detail_samples, max_products=products,
                    timeout_seconds=15, max_runtime_seconds=120, delay_seconds=0.5)
    transport = Transport(domain, limits)
    adapter = RockinOutRecordsAdapter(domain)
    listing = collect(adapter, transport, first_url, limits)
    details = []
    for row in listing["listings"][:detail_samples]:
        url = row["url"]
        detail = adapter.parse_detail(transport.get(url), source_url=url, listing=row)
        details.append({"url": url, **detail})
    return {"schema_version": 1, "shop": domain, "category_url": first_url,
            "observed_at": datetime.now(timezone.utc).isoformat(), "listing": listing,
            "detail_samples": details, "ean_found": sum(bool(x.get("identifier_raw")) for x in details)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--products", type=int, default=20)
    parser.add_argument("--detail-samples", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.pages <= 5 or not 1 <= args.products <= 50 or not 1 <= args.detail_samples <= 3:
        parser.error("pages must be 1..5, products 1..50 and detail-samples 1..3")
    result = run(pages=args.pages, products=args.products, detail_samples=args.detail_samples)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Rockin' Out pilot: {len(result['listing']['listings'])} listings, {result['ean_found']} EAN details")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
