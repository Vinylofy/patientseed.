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
        py.write_text(
            f'"""Generated scraper profile for {domain}; adapter contract tested by a manual Action run."""\n'
            f"from {module} import {adapter_name}\n\n"
            f"DOMAIN = {domain!r}\nCATALOG_ROUTE = {source_url!r}\n\n"
            f"class {generated_class}:\n"
            f"    domain = DOMAIN\n    catalog_route = CATALOG_ROUTE\n"
            f"    adapter_class = {adapter_name}\n\n"
            f"    def __init__(self):\n        self.adapter = {adapter_name}(DOMAIN)\n\n"
            f"    def parse_listing(self, body, *, observed_at):\n"
            f"        return self.adapter.parse_listing(body, source_url=CATALOG_ROUTE, observed_at=observed_at)\n\n"
            f"    def parse_detail(self, body, *, source_url, listing):\n"
            f"        return self.adapter.parse_detail(body, source_url=source_url, listing=listing)\n",
            encoding="utf-8")
        profile.write_text(json.dumps({"schema_version": 1, "domain": domain, "platform": platform,
                                       "adapter_class": adapter_name, "catalog_route": source_url,
                                       "listing_sample": row.get("accepted", 0),
                                       "detail_checked": row["detail_checked"],
                                       "detail_gtin_valid": row.get("detail_gtin_valid", 0),
                                       "release_status": "SCRAPER_BUILT_TESTED"},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
