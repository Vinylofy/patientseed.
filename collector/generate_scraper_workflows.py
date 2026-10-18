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
    return f'''name: SCRAPER | {label} | {name}

run-name: SCRAPER | {name} | {label}

on:
  workflow_dispatch:
    inputs:
      limit:
        description: "Maximum records"
        required: true
        default: "250"
        type: string

permissions:
  contents: write

jobs:
  scraper:
    uses: ./.github/workflows/scraper-single-reusable.yml
    with:
      scraper_slug: {name}
      mode: {mode}
      limit: ${{{{ inputs.limit }}}}
'''


def render_shard(mode: str, shard_number: int, names: list[str]) -> str:
    # Admission is selected at runtime from exact validated profiles. Newly
    # approved shops need no GITHUB_TOKEN workflow-file mutation.
    label = "Price" if mode == "price" else "EAN"
    cron = "17 2 */2 * *" if mode == "price" else "17 3 * * *"
    return f'''name: SCRAPER | Scheduled | {label} | Shard {shard_number:02d}

on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch:
    inputs:
      limit:
        description: "Maximum records per admitted scraper"
        required: true
        default: "250"
        type: string

permissions:
  contents: write

concurrency:
  group: scraper-{mode}-shard-{shard_number:02d}
  cancel-in-progress: false

jobs:
  select:
    runs-on: ubuntu-24.04
    outputs:
      chunks: ${{{{ steps.plan.outputs.chunks }}}}
      has_work: ${{{{ steps.plan.outputs.has_work }}}}
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          persist-credentials: false
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          ref: scraper-builds
          path: published
          persist-credentials: false
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          ref: scraper-quality
          path: release
          persist-credentials: false
      - name: Select exact quality-approved releases
        id: plan
        run: |
          chunks=$(python -m collector.quality_gate --profiles published/collector/generated --state-root release/quality --plan)
          echo "chunks=$chunks" >> "$GITHUB_OUTPUT"
          if [ "$chunks" = "[]" ]; then echo "has_work=false" >> "$GITHUB_OUTPUT"; else echo "has_work=true" >> "$GITHUB_OUTPUT"; fi
  scraper:
    needs: select
    if: needs.select.outputs.has_work == 'true'
    strategy:
      fail-fast: false
      max-parallel: 2
      matrix:
        include: ${{{{ fromJSON(needs.select.outputs.chunks) }}}}
    uses: ./.github/workflows/scraper-approved-shard.yml
    with:
      slugs: ${{{{ toJSON(matrix.slugs) }}}}
      mode: {mode}
      limit: ${{{{ inputs.limit || '250' }}}}
'''


def existing_names(output: Path) -> set[str]:
    names: set[str] = set()
    for path in output.glob("scraper-*.yml"):
        stem = path.stem.removeprefix("scraper-")
        if stem in {"price-refresh", "ean-refresh"}:
            continue
        if stem.startswith("price-") and not stem.startswith("price-shard-"):
            names.add(stem.removeprefix("price-"))
            continue
        if stem.startswith("price-shard-"):
            continue
        if stem.startswith("ean-") and not stem.startswith("ean-shard-"):
            names.add(stem.removeprefix("ean-"))
            continue
        if stem.startswith("ean-shard-"):
            continue
        if stem.startswith(("single", "health", "legacy")):
            continue
        names.add(stem)
    return names


def sync_shards(output: Path, names: set[str]) -> list[Path]:
    created: list[Path] = []
    ordered = sorted(names)
    for mode in ("price", "ean"):
        for offset in range(0, len(ordered), 100):
            shard_number = offset // 100 + 1
            path = output / f"scraper-{mode}-shard-{shard_number:02d}.yml"
            path.write_text(render_shard(mode, shard_number, ordered[offset:offset + 100]), encoding="utf-8")
            created.append(path)
    return created


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
    all_names = existing_names(output)
    for profile in profile_root.glob("*.json"):
        data = json.loads(profile.read_text(encoding="utf-8"))
        name = slug(str(data.get("domain", profile.stem)))
        if name:
            all_names.add(name)
    for name in sorted(all_names):
        for mode in ("price", "ean"):
            path = output / f"scraper-{mode}-{name}.yml"
            if not path.exists():
                path.write_text(render(name, mode), encoding="utf-8")
                created.append(path)
    created.extend(sync_shards(output, all_names))
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
