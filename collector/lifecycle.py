"""Persist scraper lifecycle decisions and freeze exhausted shops safely."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "shop"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "max_attempts": 3, "shops": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("shops"), dict):
        raise ValueError("invalid scraper lifecycle state")
    return value


def render(state: dict) -> str:
    rows = sorted(state["shops"].values(), key=lambda item: (item.get("row", 0), item["domain"]))
    lines = ["# Scraper lifecycle status", "", f"Maximale bouwpogingen: {state.get('max_attempts', 3)}", "",
             "| Shop | Rij | Pogingen | Status | Prijs | EAN | 2e hands | Laatste bewijs |", "|---|---:|---:|---|---|---|---|---|"]
    for item in rows:
        lines.append("| " + " | ".join(str(item.get(key, "—")).replace("|", "\\|") for key in (
            "domain", "row", "attempts", "status", "prices_verified", "ean_verified", "second_hand_verified", "evidence")) + " |")
    return "\n".join(lines) + "\n"


def update(result_path: Path, state_path: Path, frozen_root: Path, *, max_attempts: int = 3) -> dict:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("complete") is not True:
        raise ValueError("only a complete collector result can update lifecycle state")
    state = load(state_path)
    state["max_attempts"] = max_attempts
    state["last_run_id"] = result.get("run_id", "manual")
    state["updated_at"] = now()
    frozen_root.mkdir(parents=True, exist_ok=True)
    for item in result.get("results", []):
        domain = item.get("domain")
        if not isinstance(domain, str) or not domain:
            continue
        previous = state["shops"].get(domain, {})
        success = item.get("status") == "SCRAPER_BUILT_TESTED"
        attempts = int(previous.get("attempts", 0)) + (0 if success and previous.get("status") == "SCRAPER_BUILT_TESTED" else 1)
        status = "SCRAPER_BUILT_TESTED" if success else ("FROZEN" if attempts >= max_attempts else item.get("status", "PENDING"))
        evidence = item.get("generated_files") or item.get("reason") or item.get("source_url") or ""
        record = {**previous, **item, "domain": domain, "attempts": attempts, "status": status,
                  "evidence": evidence, "last_attempt_at": now()}
        state["shops"][domain] = record
        if status == "FROZEN":
            directory = frozen_root / slug(domain)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "status.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state_path.with_suffix(".md").write_text(render(state), encoding="utf-8")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.max_attempts <= 3:
        parser.error("max-attempts must be between 1 and 3")
    state = update(args.result, args.state, args.frozen_root, max_attempts=args.max_attempts)
    print(f"Updated lifecycle state for {len(state['shops'])} shops")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
