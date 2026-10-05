"""Render one central shop-status document from the durable public cursor."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from collector.manual_run import load_queue
from collector.progress import next_index


def cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def next_step(result: dict) -> str:
    status = result.get("status", "PENDING")
    step = {"PENDING": "broncontrole uitvoeren", "SOURCE_REVIEW": "bronidentiteit beoordelen",
            "SOURCE_BLOCKED": "toegang gericht hercontroleren", "PLATFORM_REVIEW": "platform en route onderzoeken",
            "PLATFORM_IDENTIFIED": "catalogusroute vaststellen", "ROUTE_REVIEW": "catalogusroute beoordelen",
            "CATALOG_ROUTE_VERIFIED": "listingcontract of adapter valideren",
            "ADAPTER_TESTED": "detailproef en EAN controleren",
            "LISTING_SAMPLE": "detail/EAN en private QA beoordelen",
            "SCRAPER_BUILT_TESTED": "private QA en marktgate beoordelen"}.get(status, "status beoordelen")
    reason = result.get("reason")
    return f"{step}: {reason}" if reason else step


def render(queue: list[dict], state: dict) -> str:
    cursor = next_index(state, queue)
    history = state.get("history")
    if (not isinstance(history, list) or len(history) != cursor
            or [item.get("row") for item in history] != [item["row"] for item in queue[:cursor]]):
        raise ValueError("saved history does not match the reviewed queue prefix")
    counts = Counter(item["status"] for item in history)
    lines = ["# Centrale scraperstatus", "",
             f"Bronregels: {len(queue)}. Behandeld voor broncontrole: {cursor}. "
             f"Open voor broncontrole: {len(queue) - cursor}.", "",
             "Een bronproef is geen volledig gebouwde scraper. EAN-cijfers zijn alleen kleine checksumproeven; "
             "private acceptatie, marktprijzen en imports volgen apart.", "",
             "## Statusaantallen", ""]
    lines.extend(f"- {cell(status)}: {count}" for status, count in sorted(counts.items()))
    lines.extend(["", "## Winkels", "",
                  "| Queue | Batch | Excelrij | Winkel | Domein | Platform | Bronstatus | Listing | Detail/GTIN | Volgende stap |",
                  "|---:|---:|---:|---|---|---|---|---:|---|---|"])
    for position, item in enumerate(queue):
        result = history[position] if position < cursor else {}
        detail = (f"{result.get('detail_gtin_valid', 0)}/{result.get('detail_checked', 0)} geldig"
                  if "detail_checked" in result else "—")
        lines.append("| " + " | ".join(cell(value) for value in (
            position, result.get("batch", ""), item["row"], item["name"], item["domain"],
            result.get("platform", ""), result.get("status", "PENDING"), result.get("accepted", ""),
            detail, next_step(result))) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    queue = load_queue(args.queue)
    state = json.loads(args.progress.read_text(encoding="utf-8"))
    args.output.write_text(render(queue, state), encoding="utf-8")
    print(f"Rendered one status list with {len(queue)} shop rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
