"""Run published scraper profiles in a bounded, database-free read-only mode."""
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.transport import Transport, public_source


def load_profile(path: Path) -> tuple[dict, object]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    py = path.with_suffix(".py")
    spec = importlib.util.spec_from_file_location(f"published_{path.stem}", py)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    classes = [value for value in vars(module).values() if isinstance(value, type) and value.__name__.startswith("Generated")]
    if len(classes) != 1:
        raise ValueError(f"expected one generated scraper in {py}")
    return profile, classes[0]()


def run(root: Path, mode: str, limit: int) -> dict:
    assert_credential_free_environment()
    started = datetime.now(timezone.utc).isoformat()
    rows, errors, profiles = [], [], []
    for profile_path in sorted(root.glob("*.json")):
        profile_result = {"profile": profile_path.name, "status": "not_run_limit" if len(rows) >= limit else "success",
                          "records": 0, "ean_records": 0, "errors": [], "detail_errors": 0,
                          "truncated": False}
        if len(rows) >= limit:
            profiles.append(profile_result)
            continue
        try:
            profile, scraper = load_profile(profile_path)
            domain = profile["domain"]
            route = profile["catalog_route"]
            public_source(route, domain)
            transport = Transport(domain, Limits(max_pages=1, max_requests=max(4, limit + 1),
                                                   max_products=max(1, limit), timeout_seconds=15,
                                                   max_runtime_seconds=300, delay_seconds=1.0))
            listing = scraper.parse_listing(transport.get(route), source_url=route, observed_at=started)
            for item in listing.listings:
                if len(rows) >= limit:
                    break
                record = {"domain": domain, "source_url": item["url"], "title": item.get("title"),
                          "artist": item.get("artist"), "price": item.get("price"),
                          "currency": item.get("currency"), "condition": item.get("condition"),
                          "second_hand": item.get("condition") != "new", "observed_at": started}
                if mode == "ean":
                    try:
                        detail = scraper.parse_detail(transport.get(item["url"]), source_url=item["url"], listing=item)
                        record["ean"] = detail.get("identifier_raw")
                        record["identifier_type"] = detail.get("identifier_type")
                    except (CollectionBlocked, OSError, TimeoutError, ValueError) as exc:
                        record["detail_error"] = type(exc).__name__
                        profile_result["detail_errors"] += 1
                rows.append(record)
                profile_result["records"] += 1
                if record.get("ean"):
                    profile_result["ean_records"] += 1
            profile_result["truncated"] = len(rows) >= limit
        except (CollectionBlocked, OSError, TimeoutError, ValueError, KeyError) as exc:
            error = {"profile": profile_path.name, "error": type(exc).__name__, "reason": str(exc)[:200]}
            errors.append(error)
            profile_result["status"] = "failure"
            profile_result["errors"].append(error)
        profiles.append(profile_result)
    return {"schema_version": 1, "mode": mode, "limit": limit, "started_at": started,
            "records": rows, "errors": errors, "profiles": profiles, "database_write": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("price", "ean"), required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    result = run(args.root, args.mode, args.limit)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected {len(result['records'])} read-only {args.mode} records; errors={len(result['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
