"""Create separate manual price and EAN workflow wrappers for each profile."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def render(name: str, mode: str) -> str:
    label = "Price" if mode == "price" else "EAN"
    return f'''name: SCRAPER | {name}

run-name: SCRAPER | {name} | {label}

on:
  workflow_dispatch:
    inputs:
      limit:
        description: "Maximum records"
        required: true
        default: "250"
        type: string

jobs:
  scraper:
    uses: ./.github/workflows/scraper-single-reusable.yml
    with:
      scraper_slug: {name}
      mode: {mode}
      limit: ${{{{ inputs.limit }}}}
'''


def generate(profile_root: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    created = []
    for profile in sorted(profile_root.glob("*.json")):
        data = json.loads(profile.read_text(encoding="utf-8"))
        name = slug(str(data.get("domain", profile.stem)))
        if not name:
            continue
        for mode in ("price", "ean"):
            path = output / f"scraper-{mode}-{name}.yml"
            if not path.exists():
                path.write_text(render(name, mode), encoding="utf-8")
                created.append(path)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    created = generate(args.profiles, args.output)
    print(f"Generated {len(created)} new per-scraper workflow wrappers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
