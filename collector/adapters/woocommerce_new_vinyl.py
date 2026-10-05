"""Conservative adapter for verified public WooCommerce Store API routes."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source


class _JsonLd(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts: list[str] = []
        self.items: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active, self.parts = True, []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.items.append("".join(self.parts))
            self.active = False


def attribute_values(product: dict, key: str) -> set[str]:
    values = set()
    attributes = product.get("attributes")
    for attribute in attributes if isinstance(attributes, list) else []:
        if not isinstance(attribute, dict) or str(attribute.get("name", "")).casefold() != key:
            continue
        terms = attribute.get("terms")
        for term in terms if isinstance(terms, list) else []:
            if isinstance(term, dict) and isinstance(term.get("name"), str):
                values.add(term["name"].strip().casefold())
    return values


class WooCommerceNewVinylAdapter:
    def __init__(self, domain: str):
        self.domain = domain

    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url, self.domain)
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise CollectionBlocked("WooCommerce Store API contract changed")
        rows, exclusions = [], []
        for product in payload:
            if not isinstance(product, dict) or type(product.get("id")) is not int:
                continue
            url = product.get("permalink")
            if not isinstance(url, str):
                continue
            public_source(url, self.domain)
            condition = attribute_values(product, "condition")
            formats = attribute_values(product, "format") | attribute_values(product, "media")
            if condition != {"new"} or not (formats & {"vinyl", "lp", "12 inch", "7 inch"}):
                exclusions.append({"url": url, "signal": "new_vinyl_not_proven", "at": observed_at})
                continue
            prices = product.get("prices")
            if not isinstance(prices, dict) or type(product.get("is_in_stock")) is not bool:
                exclusions.append({"url": url, "signal": "listing_price_or_stock_unproven", "at": observed_at})
                continue
            code, minor = prices.get("currency_code"), prices.get("currency_minor_unit")
            raw = prices.get("price")
            if (not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code)
                    or type(minor) is not int or not 0 <= minor <= 3
                    or not isinstance(raw, str) or not raw.isascii() or not raw.isdigit()):
                exclusions.append({"url": url, "signal": "listing_price_or_currency_unproven", "at": observed_at})
                continue
            try:
                price = Decimal(raw) / (Decimal(10) ** minor)
            except InvalidOperation as exc:
                raise CollectionBlocked("Invalid WooCommerce price") from exc
            if price <= 0:
                exclusions.append({"url": url, "signal": "nonpositive_price", "at": observed_at})
                continue
            title = product.get("name")
            if not isinstance(title, str) or not title.strip():
                exclusions.append({"url": url, "signal": "title_unproven", "at": observed_at})
                continue
            rows.append({"url": url, "artist": "", "title": title, "identifier_raw": None,
                         "identifier_type": "unknown", "identifier_source_url": url,
                         "price": f"{price:.2f}", "base_price": f"{price:.2f}", "sale_price": None,
                         "currency": code, "availability": "in_stock" if product["is_in_stock"] else "out_of_stock",
                         "observed_at": observed_at, "price_source_url": source_url, "price_source": "listing",
                         "availability_source": "listing", "product_type": "vinyl", "condition": "new",
                         "condition_source_url": source_url,
                         "price_context": {"vat": "unknown", "kind": "public", "variant": str(product["id"]),
                                           "buyable_variant": True, "units": 1, "bundle": False,
                                           "membership": False, "mandatory_surcharge": "0", "from_price": False},
                         "source_fragment": json.dumps({"id": product["id"], "name": title})})
        return ListingPage(tuple(rows), None, tuple(exclusions))

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, self.domain)
        if urlsplit(source_url).path != urlsplit(listing["url"]).path:
            raise CollectionBlocked("Detail product mismatch")
        parser = _JsonLd()
        parser.feed(body)
        codes = set()
        for raw in parser.items:
            try:
                value = json.loads(raw)
            except ValueError:
                continue
            for node in value if isinstance(value, list) else [value]:
                if not isinstance(node, dict) or node.get("@type") != "Product":
                    continue
                codes.update(node[key] for key in ("gtin", "gtin12", "gtin13", "gtin14")
                             if isinstance(node.get(key), str))
        if len(codes) != 1:
            return {}
        code = next(iter(codes))
        kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(code))
        return ({"identifier_raw": code, "identifier_type": kind, "identifier_source_url": source_url}
                if kind and code.isascii() and code.isdigit() else {})
