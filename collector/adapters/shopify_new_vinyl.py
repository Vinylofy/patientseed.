"""Conservative Shopify JSON product-feed adapter for approved public shops."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from decimal import Decimal
from urllib.parse import urlsplit

from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source


class _JsonLd(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.buf = []; self.items = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json": self.active = True; self.buf = []
    def handle_data(self, data):
        if self.active: self.buf.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.items.append("".join(self.buf)); self.active = False


class ShopifyNewVinylAdapter:
    def __init__(self, domain: str):
        if not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise CollectionBlocked("Invalid Shopify domain")
        self.domain = domain

    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url, self.domain)
        payload = json.loads(body)
        if set(payload) != {"products"} or not isinstance(payload["products"], list):
            raise CollectionBlocked("Shopify feed contract changed")
        rows, exclusions = [], []
        for product in payload["products"]:
            handle = product.get("handle")
            if not isinstance(handle, str) or not handle or "/" in handle or any(ord(ch) < 32 for ch in handle):
                exclusions.append({"url": "", "signal": "invalid_product_handle", "at": observed_at}); continue
            url = f"https://{self.domain}/products/{handle}"
            tags = product.get("tags", [])
            if isinstance(tags, str): tags = tags.split(",")
            evidence = " ".join([str(product.get("title", "")), str(product.get("product_type", "")), " ".join(map(str, tags))]).lower()
            used = bool(re.search(r"\b(used|pre[- ]?owned|second[- ]hand|vintage|graded|vg\+?|nm)\b", evidence))
            vinyl = bool(re.search(r"\b(vinyl|lp|12 inch|7 inch)\b", evidence))
            nonvinyl = bool(re.search(r"\b(cd|cassette|dvd|blu[- ]?ray|merchandise|equipment)\b", evidence))
            product_type = str(product.get("product_type", "")).strip().lower()
            new = (product_type in {"new", "new records", "new vinyl", "vinyl", "lp", "12\"", "2x12\""}
                   or bool(re.search(r"\bnew\s+(?:lp|vinyl|record)s?\b", str(product.get("title", "")), re.I))
                   or any(str(t).strip().lower() in {"new", "new vinyl", "new lp", "new arrivals", "condition:new"} for t in tags))
            if used or not vinyl or nonvinyl or not new:
                exclusions.append({"url": url, "signal": "new_vinyl_not_proven" if not used else "used", "at": observed_at})
                continue
            variants = product.get("variants")
            if not isinstance(variants, list) or not variants:
                exclusions.append({"url": url, "signal": "variant_not_proven", "at": observed_at}); continue
            title = str(product.get("title", "")); split = re.split(r"\s[|–—-]\s", title, maxsplit=1)
            if len(split) != 2: split = ("", title)
            for variant in variants:
                if type(variant.get("available")) is not bool or not variant.get("id"):
                    exclusions.append({"url": url, "signal": "availability_not_proven", "at": observed_at}); continue
                price = variant.get("price")
                if not isinstance(price, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", price) or Decimal(price) <= 0: raise CollectionBlocked("Invalid Shopify price")
                barcode = variant.get("barcode") if isinstance(variant.get("barcode"), str) else None
                kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(barcode or ""), "unknown")
                rows.append({"url": f"{url}?variant={variant['id']}", "artist": split[0], "title": split[1], "identifier_raw": barcode, "identifier_type": kind, "identifier_source_url": url, "price": f"{Decimal(price):.2f}", "base_price": f"{Decimal(price):.2f}", "sale_price": None, "currency": "USD", "availability": "in_stock" if variant["available"] else "out_of_stock", "observed_at": observed_at, "price_source_url": source_url, "price_source": "listing", "availability_source": "listing", "product_type": "vinyl", "condition": "new", "condition_source_url": url, "price_context": {"vat": "unknown", "kind": "public", "variant": str(variant["id"]), "buyable_variant": True, "units": 1, "bundle": False, "membership": False, "mandatory_surcharge": "0", "from_price": False}, "source_fragment": json.dumps({"title": title, "variant": {k: variant.get(k) for k in ("id", "price", "available", "barcode")}})})
        next_url = None if not payload["products"] else f"{source_url.split('?')[0]}?limit=20&page={int(dict(x.split('=') for x in urlsplit(source_url).query.split('&') if '=' in x).get('page', '1')) + 1}"
        return ListingPage(tuple(rows), next_url, tuple(exclusions))

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, self.domain)
        if urlsplit(source_url).path != urlsplit(listing["url"]).path: raise CollectionBlocked("Detail product mismatch")
        parser = _JsonLd(); parser.feed(body); found = []
        for raw in parser.items:
            try: value = json.loads(raw)
            except ValueError: continue
            nodes = value if isinstance(value, list) else [value]
            for node in nodes:
                if not isinstance(node, dict) or node.get("@type") != "Product": continue
                codes = [node[key] for key in ("gtin", "gtin12", "gtin13", "gtin14") if isinstance(node.get(key), str)]
                found.extend(code for code in codes if code.isascii() and code.isdigit())
        if len(set(found)) != 1: return {}
        code = found[0]; kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(code))
        return {} if kind is None else {"identifier_raw": code, "identifier_type": kind, "identifier_source_url": source_url}
