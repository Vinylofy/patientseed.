from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone

from collector.adapters.catalog import adapter_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded public collector pilot manually.")
    parser.add_argument("--queue", required=True, help="JSON file containing the public adapter queue")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--batch-limit", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.batch_limit <= 100:
        parser.error("batch-limit must be between 1 and 100")
    queue = json.loads(open(args.queue, encoding="utf-8").read())
    if not isinstance(queue, list) or any(not isinstance(domain, str) for domain in queue): parser.error("queue must be a JSON string array")
    if args.start_index < 0: parser.error("start-index must be non-negative")
    domains = [domain.strip().lower().removeprefix("www.") for domain in queue[args.start_index:] if domain.strip()]
    results = []
    for domain in domains[:args.batch_limit]:
        adapter = adapter_for(domain)
        if adapter is None:
            results.append({"domain": domain, "status": "NO_ASSIGNED_ADAPTER"})
            continue
        url = f"https://{domain}/products.json?limit=20&page=1"
        response = subprocess.run(["curl", "-L", "--max-time", "15", "--silent", "--show-error", url], capture_output=True, text=True, check=False)
        if response.returncode or not response.stdout:
            results.append({"domain": domain, "status": "TRANSPORT_BLOCKED", "code": response.returncode})
            continue
        try:
            page = adapter.parse_listing(response.stdout, source_url=url, observed_at=datetime.now(timezone.utc).isoformat())
            results.append({"domain": domain, "status": "LISTING_PILOT", "accepted": len(page.listings), "excluded": len(page.exclusions)})
        except Exception as exc:
            results.append({"domain": domain, "status": "CONTRACT_BLOCKED", "reason": type(exc).__name__})
    print(json.dumps({"start_index": args.start_index, "batch_limit": args.batch_limit, "requested": len(domains), "processed": len(results), "next_start_index": args.start_index + len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
