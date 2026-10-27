"""Generate and validate durable per-shop scraper wrappers from a tested run."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

ALLOWED_PLATFORMS = {"shopify": "ShopifyNewVinylAdapter", "woocommerce": "WooCommerceNewVinylAdapter",
                    "squarespace": "SquarespaceNewVinylAdapter", "bigcommerce": "BigCommerceNewVinylAdapter"}


def slug(domain: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")
    if not value or not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError("unsafe generated scraper name")
    return value


def source_module(platform: str) -> str:
    return {"shopify": "collector.adapters.shopify_new_vinyl",
            "woocommerce": "collector.adapters.woocommerce_new_vinyl",
            "squarespace": "collector.adapters.squarespace_new_vinyl",
            "bigcommerce": "collector.adapters.bigcommerce_new_vinyl"}[platform]


def class_name(name: str) -> str:
    return "Generated" + "".join(part.capitalize() for part in name.split("_")) + "Scraper"


def build(result_path: Path, output: Path) -> list[dict]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("complete") is not True:
        raise ValueError("only a complete run can build scrapers")
    output.mkdir(parents=True, exist_ok=True)
    built = []
    for row in result.get("results", []):
        platform = row.get("platform")
        if (row.get("status") != "ADAPTER_TESTED" or platform not in ALLOWED_PLATFORMS
                or type(row.get("detail_checked")) is not int or row["detail_checked"] < 1
                or not isinstance(row.get("source_url"), str)):
            continue
        domain = row.get("domain")
        name = slug(domain)
        adapter_name = ALLOWED_PLATFORMS[platform]
        module = source_module(platform)
        source_url = row["source_url"]
        if not source_url.startswith(f"https://{domain}/"):
            raise ValueError("generated scraper source escapes its shop")
        py = output / f"{name}.py"
        profile = output / f"{name}.json"
        generated_class = class_name(name)
        currency = row.get("currency") if platform == "shopify" else None
        if currency is not None and not re.fullmatch('[A-Z]{3}', currency):
            raise ValueError('invalid proven storefront currency')
        artist_title = row.get('scraper_type') == 'ARTIST_TITLE'
        overlay_import = 'from collector.artist_title import ArtistTitleAdapter\n' if artist_title else ''
        constructor = f"ArtistTitleAdapter({adapter_name}(DOMAIN), {platform!r})" if artist_title else f"{adapter_name}(DOMAIN)"
        py.write_text(
            f'"""Generated scraper profile for {domain}; adapter contract tested by a manual Action run."""\n'
            f"from {module} import {adapter_name}\nfrom dataclasses import replace\n{overlay_import}\n"
            f"DOMAIN = {domain!r}\nCATALOG_ROUTE = {source_url!r}\nCURRENCY = {currency!r}\n\n"
            f"class {generated_class}:\n"
            f"    domain = DOMAIN\n    catalog_route = CATALOG_ROUTE\n"
            f"    adapter_class = {adapter_name}\n\n"
            f"    def __init__(self):\n        self.adapter = {constructor}\n\n"
            f"    def parse_listing(self, body, *, source_url=None, observed_at):\n"
            f"        page = self.adapter.parse_listing(body, source_url=source_url or CATALOG_ROUTE, observed_at=observed_at)\n"
            f"        return replace(page, listings=tuple({{**item, 'currency': CURRENCY}} for item in page.listings)) if CURRENCY else page\n\n"
            f"    def parse_detail(self, body, *, source_url, listing):\n"
            f"        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)\n",
            encoding="utf-8")
        profile.write_text(json.dumps({"schema_version": 1, "domain": domain, "platform": platform,
                                       "adapter_class": adapter_name, "catalog_route": source_url,
                                       "discovery_method": row.get("selected_method", {}),
                                       "method_candidates": row.get("method_candidates", []),
                                       "listing_sample": row.get("accepted", 0),
                                       "detail_checked": row["detail_checked"],
                                       "detail_gtin_valid": row.get("detail_gtin_valid", 0),
                                       "currency": currency, "currency_source": row.get("currency_source"),
                                       "currency_source_url": row.get("currency_source_url"),
                                       "release_status": "SCRAPER_BUILT_TESTED"},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if row.get('assessment_version'):
            metadata = json.loads(profile.read_text(encoding='utf-8'))
            metadata.update(scraper_type=row['scraper_type'], assessment_version=row['assessment_version'],
                            assessment_id=row['assessment_id'], country=row.get('country'),
                            release_status='AWAITING_MANUAL_TEST', production_approved=False)
            profile.write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        spec = importlib.util.spec_from_file_location(f"generated_{name}", py)
        if spec is None or spec.loader is None:
            raise ValueError("generated scraper could not be imported")
        module_obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module_obj)
        instance = getattr(module_obj, generated_class)()
        if instance.domain != domain or instance.adapter_class.__name__ != adapter_name:
            raise ValueError("generated scraper self-test failed")
        row["status"] = "SCRAPER_BUILT_TESTED"
        row["gate"] = "qa"
        row["generated_files"] = [str(py.relative_to(output)), str(profile.relative_to(output))]
        row["build_test"] = "wrapper_import_and_contract_passed"
        built.append(row)
    result["built_scrapers"] = len(built)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return built


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    built = build(args.result, args.output)
    print(f"Built and self-tested {len(built)} scraper wrappers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
