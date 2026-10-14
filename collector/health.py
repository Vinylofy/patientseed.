"""Track published scraper health and queue only consecutive failures for repair."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "shop"


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "modes": {"price": {}, "ean": {}}, "repair_queue": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("modes"), dict):
        raise ValueError("invalid scraper health state")
    value.setdefault("repair_queue", [])
    return value


def render(state: dict) -> str:
    lines = ["# Scraper health status", "", "Een enkele fout wordt als incidenteel behandeld. Twee opeenvolgende fouten zetten een scraper in de repair-queue.", "",
             "| Modus | Domein | Status | Opeenvolgende fouten | Herstelpogingen | Laatste fout |", "|---|---|---|---:|---:|---|"]
    for mode in ("price", "ean"):
        for domain, item in sorted(state["modes"].get(mode, {}).items()):
            lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in (
                mode, domain, item.get("status", "UNKNOWN"), item.get("consecutive_failures", 0),
                item.get("repair_attempts", 0), item.get("last_failure_reason", "—"))) + " |")
    lines.extend(["", f"Repair-queue: {len(state.get('repair_queue', []))} scrapers", ""])
    return "\n".join(lines)


def _profile_expected(profile_root: Path, filename: str) -> tuple[str, int]:
    profile = json.loads((profile_root / filename).read_text(encoding="utf-8"))
    return profile["domain"], int(profile.get("listing_sample", 0))


def _is_good(mode: str, observation: dict, expected: int) -> bool:
    if observation.get("status") != "success" or observation.get("truncated"):
        return False
    records = int(observation.get("records", 0))
    if expected > 0 and records == 0:
        return False
    if mode == "ean" and records > 0 and int(observation.get("detail_errors", 0)) >= records:
        return False
    return True


def update(result_path: Path, state_path: Path, profile_root: Path, *, run_id: str = "unknown",
           max_repair_attempts: int = 3) -> dict:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("mode") not in {"price", "ean"}:
        raise ValueError("invalid scraper refresh result")
    state = load(state_path)
    mode = result["mode"]
    state["updated_at"] = now()
    state["last_run_id"] = run_id
    state["last_mode"] = mode
    bucket = state["modes"].setdefault(mode, {})
    queued = {(item["mode"], item["domain"]) for item in state.get("repair_queue", [])}
    for observation in result.get("profiles", []):
        if observation.get("status") == "not_run_limit":
            continue
        try:
            domain, expected = _profile_expected(profile_root, observation["profile"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        previous = bucket.get(domain, {})
        good = _is_good(mode, observation, expected)
        consecutive = 0 if good else int(previous.get("consecutive_failures", 0)) + 1
        repair_attempts = int(previous.get("repair_attempts", 0))
        status = "ACTIVE" if good else ("REPAIR_REQUIRED" if consecutive >= 2 and repair_attempts < max_repair_attempts else "INCIDENT")
        if good:
            record = {**previous, "status": status, "consecutive_failures": 0,
                      "last_known_good": now(), "last_good_records": observation.get("records", 0),
                      "last_good_run_id": run_id}
            queued.discard((mode, domain))
        else:
            reason = (observation.get("errors") or [{"reason": "quality check failed"}])[0].get("reason", "quality check failed")
            record = {**previous, "status": status, "consecutive_failures": consecutive,
                      "last_failure_at": now(), "last_failure_reason": reason,
                      "last_failure_run_id": run_id, "last_observation": observation}
            if status == "REPAIR_REQUIRED":
                queued.add((mode, domain))
        bucket[domain] = record
    state["repair_queue"] = [{"mode": mode_name, "domain": domain} for mode_name, domain in sorted(queued)]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.with_suffix(".md").write_text(render(state), encoding="utf-8")
    return state


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--run-id", default="unknown")
    args = parser.parse_args()
    state = update(args.result, args.state, args.profiles, run_id=args.run_id)
    print(f"Tracked health for {sum(len(value) for value in state['modes'].values())} scraper/mode pairs; queue={len(state['repair_queue'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
