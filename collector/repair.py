"""Repair up to a bounded number of consecutive scraper failures."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.health import load as load_health, now
from collector.transport import Transport, public_source
from collector.execute_generated import load_profile, parse_listing


def _routes(profile: dict) -> list[str]:
    values = [profile.get("catalog_route")]
    values.extend(candidate.get("route") for candidate in profile.get("method_candidates", [])
                  if isinstance(candidate, dict) and candidate.get("status") == "ADAPTER_PARSED")
    return list(dict.fromkeys(route for route in values if isinstance(route, str)))


def _try_routes(profile: dict, scraper: object) -> str | None:
    domain = profile["domain"]
    transport = Transport(domain, Limits(max_pages=1, max_requests=6, max_products=20,
                                         timeout_seconds=15, max_runtime_seconds=120, delay_seconds=1.0))
    for route in _routes(profile):
        try:
            public_source(route, domain)
            listing = parse_listing(scraper, transport.get(route), route,
                                    datetime.now(timezone.utc).isoformat())
            if not listing.listings:
                continue
            # Confirm the selected route still maps to a detail page before
            # changing the durable profile.
            first = listing.listings[0]
            scraper.parse_detail(transport.get(first["url"].split("?", 1)[0]),
                                 source_url=first["url"].split("?", 1)[0], listing=first)
            return route
        except (CollectionBlocked, OSError, TimeoutError, ValueError, TypeError, KeyError):
            continue
    return None


def _replace_route(py_path: Path, old: str, new: str) -> None:
    text = py_path.read_text(encoding="utf-8")
    updated, count = re.subn(r"^CATALOG_ROUTE = .*?$", f"CATALOG_ROUTE = {new!r}", text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"could not update catalog route in {py_path.name}")
    py_path.write_text(updated, encoding="utf-8")


def run(state_path: Path, profiles: Path, frozen_root: Path, *, limit: int, run_id: str) -> dict:
    assert_credential_free_environment()
    state = load_health(state_path)
    selected = list(state.get("repair_queue", []))[:limit]
    remaining = list(state.get("repair_queue", []))[limit:]
    repaired, failed = [], []
    for item in selected:
        mode, domain = item["mode"], item["domain"]
        record = state["modes"].setdefault(mode, {}).get(domain, {})
        profile_path = profiles / f"{re.sub(r'[^a-z0-9]+', '_', domain.lower()).strip('_')}.json"
        attempts = int(record.get("repair_attempts", 0)) + 1
        profile = None
        route = None
        try:
            if profile_path.exists():
                profile, scraper = load_profile(profile_path)
                route = _try_routes(profile, scraper)
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            route = None
        record["repair_attempts"] = attempts
        record["last_repair_run_id"] = run_id
        record["last_repair_at"] = now()
        if route:
            old = profile["catalog_route"]
            if route != old:
                _replace_route(profile_path.with_suffix(".py"), old, route)
                profile["catalog_route"] = route
                profile["repaired_at"] = now()
                profile["repair_run_id"] = run_id
                profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            record.update({"status": "ACTIVE", "consecutive_failures": 0, "repair_attempts": 0,
                           "last_repair_result": "route_revalidated"})
            repaired.append({"mode": mode, "domain": domain, "route": route})
        elif attempts >= 3:
            record.update({"status": "FROZEN", "last_repair_result": "three_repair_attempts_failed"})
            directory = frozen_root / re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "health-status.json").write_text(json.dumps({"mode": mode, "domain": domain,
                **record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            failed.append({"mode": mode, "domain": domain, "status": "FROZEN"})
        else:
            record.update({"status": "REPAIR_REQUIRED", "last_repair_result": "no_route_revalidated"})
            remaining.append(item)
            failed.append({"mode": mode, "domain": domain, "status": "RETRY"})
        state["modes"][mode][domain] = record
    state["repair_queue"] = remaining
    state["updated_at"] = now()
    state["last_repair_run_id"] = run_id
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.with_suffix(".md").write_text(__import__("collector.health", fromlist=["render"]).render(state), encoding="utf-8")
    return {"processed": len(selected), "repaired": repaired, "failed": failed, "remaining": len(remaining)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--run-id", default="unknown")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.state, args.profiles, args.frozen_root, limit=args.limit, run_id=args.run_id)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Processed {result['processed']} repairs; repaired={len(result['repaired'])}; remaining={result['remaining']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
