"""Write a compact per-scraper GitHub Actions job summary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def render(result: dict) -> str:
    mode = result.get("mode", "unknown")
    lines = [f"## SCRAPER | {mode.upper()} | resultaat", "",
             f"Records: **{len(result.get('records', []))}** · fouten: **{len(result.get('errors', []))}**", "",
             "| Scraper | Domein | Status | Records | EAN-records | Detailfouten | Prijskwaliteit |", "|---|---|---|---:|---:|---:|---|"]
    for item in result.get("profiles", []):
        quality = item.get("price_quality", {}).get("status", "—")
        lines.append("| " + " | ".join(str(item.get(key, "—")).replace("|", "\\|") for key in (
            "profile", "domain", "status", "records", "ean_records", "detail_errors")) + f" | {quality} |")
    if result.get("outcome"): lines.extend(["", f"Uitkomst: {result['outcome']}"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    content = render(json.loads(args.result.read_text(encoding="utf-8")))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(content)
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
