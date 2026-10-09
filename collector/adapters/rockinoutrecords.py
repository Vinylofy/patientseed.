"""Bounded HTML adapter for Rockin' Out Records' new-vinyl category."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source


class _CategoryParser(HTMLParser):
    def __init__(self, domain: str):
        super().__init__(convert_charrefs=True)
        self.domain = domain
        self.products: list[dict] = []
        self.next_url: str | None = None
        self.current: dict | None = None
        self.capture: str | None = None
        self.capture_tag: str | None = None
        self.capture_depth = 0
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "link" and attrs.get("rel") == "next" and attrs.get("href"):
            self.next_url = urljoin(f"https://{self.domain}/", attrs["href"])
        if tag == "li" and "product" in classes:
            self.current = {"url": None, "title": "", "price": None,
                            "out_of_stock": "outofstock" in classes, "category": ""}
        if self.current is None:
            return
        if self.capture:
            self.capture_depth += 1
            return
        if tag == "a" and attrs.get("href") and any(name in (attrs.get("class") or "")
                                                       for name in ("woocommerce-loop-product__link", "ast-loop-product__link")):
            self.current["url"] = urljoin(f"https://{self.domain}/", attrs["href"])
            self.capture = "title" if "title" in (attrs.get("class") or "") else self.capture
            if self.capture == "title": self.capture_tag = "a"
            self.text = []
        elif tag in {"h2", "h3"} and "product" in (attrs.get("class") or ""):
            self.capture = "title"; self.capture_tag = tag; self.text = []
        elif tag == "span" and "price" in classes:
            self.capture = "price"; self.capture_tag = "span"; self.text = []
        elif tag == "span" and "ast-woo-product-category" in classes:
            self.capture = "category"; self.capture_tag = "span"; self.text = []

    def handle_data(self, data: str):
        if self.current is not None and self.capture:
            self.text.append(data)

    def handle_endtag(self, tag: str):
        if self.current is None:
            return
        if self.capture:
            self.capture_depth -= 1
        if tag == self.capture_tag and self.capture and self.capture_depth <= 0:
            value = " ".join("".join(self.text).split())
            if self.capture == "title" and value:
                self.current["title"] = value
            elif self.capture == "price" and value:
                self.current["price"] = value
            elif self.capture == "category" and value:
                self.current["category"] = value
            self.capture = None; self.capture_tag = None; self.capture_depth = 0; self.text = []
        if tag == "li":
            if self.current.get("url"):
                self.products.append(self.current)
            self.current = None


class _JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.parts: list[str] = []; self.items: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active = True; self.parts = []
    def handle_data(self, data):
        if self.active: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.items.append("".join(self.parts)); self.active = False


def _price(value: str) -> str:
    match = re.search(r"[0-9][0-9.]*,[0-9]{1,2}|[0-9]+(?:\.[0-9]{1,2})?", value)
    if not match:
        raise ValueError("price not proven")
    raw = match.group(0).replace(".", "").replace(",", ".") if "," in match.group(0) else match.group(0)
    amount = Decimal(raw)
    if amount <= 0: raise ValueError("nonpositive price")
    return f"{amount:.2f}"


class RockinOutRecordsAdapter:
    def __init__(self, domain: str = "rockinoutrecords.nl"):
        self.domain = domain

    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url, self.domain)
        parser = _CategoryParser(self.domain); parser.feed(body)
        rows, exclusions = [], []
        for product in parser.products:
            url = product["url"]
            text = unescape(f"{product['title']} {product['category']}").lower()
            if "vinyl" not in text and "lp" not in text:
                exclusions.append({"url": url, "signal": "vinyl_not_proven", "at": observed_at}); continue
            try: price = _price(product["price"] or "")
            except ValueError:
                exclusions.append({"url": url, "signal": "price_not_proven", "at": observed_at}); continue
            rows.append({"url": url, "artist": "", "title": unescape(product["title"]),
                         "identifier_raw": None, "identifier_type": "unknown", "identifier_source_url": url,
                         "price": price, "base_price": price, "sale_price": None, "currency": "EUR",
                         "availability": "out_of_stock" if product["out_of_stock"] else "in_stock",
                         "observed_at": observed_at, "price_source_url": source_url, "price_source": "listing",
                         "availability_source": "listing", "product_type": "vinyl", "condition": "new",
                         "condition_source_url": source_url,
                         "price_context": {"vat": "unknown", "kind": "public", "variant": "single",
                                           "buyable_variant": not product["out_of_stock"], "units": 1,
                                           "bundle": False, "membership": False, "mandatory_surcharge": "0",
                                           "from_price": False},
                         "source_fragment": json.dumps({"title": product["title"], "url": url})})
        return ListingPage(tuple(rows), parser.next_url, tuple(exclusions))

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, self.domain)
        if urlsplit(source_url).path.rstrip("/") != urlsplit(listing["url"]).path.rstrip("/"):
            raise CollectionBlocked("Detail product mismatch")
        parser = _JsonLdParser(); parser.feed(body); codes = set()
        for raw in parser.items:
            try: value = json.loads(raw)
            except ValueError: continue
            nodes = value.get("@graph", []) if isinstance(value, dict) and isinstance(value.get("@graph"), list) else [value]
            for node in nodes:
                if not isinstance(node, dict) or node.get("@type") != "Product": continue
                for key in ("gtin", "gtin12", "gtin13", "gtin14", "ean"):
                    code = node.get(key)
                    if isinstance(code, str) and code.isascii() and code.isdigit(): codes.add(code)
        if len(codes) != 1: return {}
        code = next(iter(codes)); kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(code))
        return {"identifier_raw": code, "identifier_type": kind, "identifier_source_url": source_url} if kind else {}
