"""Bounded, parallel source reconnaissance for a public shop queue."""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from collector.contracts import assert_credential_free_environment
from collector.recon import probe
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


def run(queue: list[dict], start_index: int, batch_limit: int, *, transport_factory=Transport,
        on_progress=None) -> dict:
    if not 0 <= start_index <= len(queue) or not 1 <= batch_limit <= len(queue):
        raise ValueError("invalid start index or batch limit")
    assert_credential_free_environment()
    results = []
    selected = queue[start_index:start_index + batch_limit]

    def one(item: dict) -> dict:
        try:
            return probe(item, transport_factory)
        except Exception as exc:  # One malformed source must not prevent the next shop.
            return {"row": item["row"], "name": item["name"], "domain": item["domain"],
                    "status": "SOURCE_REVIEW", "gate": "source", "reason": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(one, selected):
            results.append(result)
            if on_progress is not None:
                on_progress(result, {"schema_version": 1, "queue_sha256": queue_digest(queue),
                                     "start_index": start_index, "batch_limit": batch_limit,
                                     "processed": len(results), "next_start_index": start_index + len(results),
                                     "queue_size": len(queue), "complete": len(results) == len(selected),
                                     "results": list(results)})
    return {"schema_version": 1, "queue_sha256": queue_digest(queue), "start_index": start_index,
            "batch_limit": batch_limit, "processed": len(results), "next_start_index": start_index + len(results),
            "queue_size": len(queue), "complete": True, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--start-index", type=int, required=True)
    parser.add_argument("--batch-limit", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        def checkpoint(item: dict, partial: dict) -> None:
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(args.output)
            print(f"Row {item['row']}: {item['status']}", flush=True)

        result = run(load_queue(args.queue), args.start_index, args.batch_limit, on_progress=checkpoint)
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not args.output.exists():
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Processed {result['processed']} of {result['queue_size']}; next index {result['next_start_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
