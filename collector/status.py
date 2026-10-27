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
            "DETAIL_GATE_BLOCKED": "detailroute of catalogus opnieuw beoordelen",
            "LISTING_SAMPLE": "detail/EAN en private QA beoordelen",
            "SCRAPER_BUILT_TESTED": "private QA en marktgate beoordelen"}.get(status, "status beoordelen")
    reason = result.get("reason")
    return f"{step}: {reason}" if reason else step


def render(queue: list[dict], state: dict, sources: list[dict] | None = None) -> str:
    cursor = next_index(state, queue)
    history = state.get("history")
    if (not isinstance(history, list) or len(history) != cursor
            or [item.get("row") for item in history] != [item["row"] for item in queue[:cursor]]):
        raise ValueError("saved history does not match the reviewed queue prefix")
    rechecks = {item["row"]: item for item in state.get("rechecks", [])}
    displayed = [rechecks.get(item["row"], history[position]) for position, item in enumerate(queue[:cursor])]
    counts = Counter(item["status"] for item in displayed)
    lines = ["# Centrale scraperstatus", "",
             f"Bronregels: {len(queue)}. Behandeld voor broncontrole: {cursor}. "
             f"Open voor broncontrole: {len(queue) - cursor}.", "",
             "Een bronproef is geen volledig gebouwde scraper. EAN-cijfers zijn alleen kleine checksumproeven; "
             "private acceptatie, marktprijzen en imports volgen apart.", "",
             "## Statusaantallen", ""]
    lines.extend(f"- {cell(status)}: {count}" for status, count in sorted(counts.items()))
    if sources:
        labelled = set()
        groups = []
        for source in sources:
            ids = {entry["row"] for entry in source["entries"]}
            if ids & labelled or not ids <= {item["row"] for item in queue}:
                raise ValueError("source manifests overlap or contain unknown queue IDs")
            labelled |= ids
            groups.append((source.get("label", source["source"]), ids))
        groups.insert(0, ("Oorspronkelijke lijst", {item["row"] for item in queue} - labelled))
        lines.extend(["", "## Brongroepen", "", "Tellingen betreffen lijstvermeldingen, niet noodzakelijk unieke winkels of unieke scraperprofielen.", "",
            "| Bron | Vermeldingen | Broncontrole afgerond | Open | Bouwstatus getest |",
            "|---|---:|---:|---:|---:|"])
        for name, ids in groups:
            examined = [result for position, result in enumerate(displayed) if queue[position]["row"] in ids]
            built = sum(result["status"] == "SCRAPER_BUILT_TESTED" for result in examined)
            lines.append(f"| {cell(name)} | {len(ids)} | {len(examined)} | {len(ids)-len(examined)} | {built} |")
        lines.append(f"| **Totaal** | **{len(queue)}** | **{cursor}** | **{len(queue)-cursor}** | **{counts.get('SCRAPER_BUILT_TESTED',0)}** |")
    lines.extend(["", "## Winkels", "",
                  "| Queue | Batch | Bronrij / ID | Winkel | Domein | Platform | Bronstatus | Listing | Detail/GTIN | Volgende stap |",
                  "|---:|---:|---:|---|---|---|---|---:|---|---|"])
    for position, item in enumerate(queue):
        result = rechecks.get(item["row"], history[position]) if position < cursor else {}
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
    source_root = args.queue.parent / "sources"
    sources = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(source_root.glob("*.json"))]
    rendered = render(queue, state, sources=sources)
    # Automated source/route rechecks must preserve the same central QA section.
    if args.output.exists():
        previous = args.output.read_text(encoding="utf-8")
        markers = ["<!-- quality-gate:start -->", "<!-- assessment-v2:start -->"]
        positions = [previous.index(marker) for marker in markers if marker in previous]
        if positions:
            rendered += "\n" + previous[min(positions):]
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Rendered one status list with {len(queue)} shop rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
