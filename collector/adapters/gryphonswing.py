from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source


DOMAIN = "gryphonswing.com"
FIRST_LISTING = "https://gryphonswing.com/products.json?limit=20&page=1"


class ProductScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.buffer = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type") == "application/ld+json"
            self.buffer = []

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.scripts.append("".join(self.buffer))
            self.active = False


def text(value: object) -> str:
    return unescape(re.sub(r"<[^>]*>", " ", str(value or "")))


def decimal_price(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise CollectionBlocked("Ambiguous feed price")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise CollectionBlocked("Invalid feed price") from exc
    if not number.is_finite() or number <= 0:
        raise CollectionBlocked("Invalid feed price")
    return f"{number:.2f}"


class GryphonsWingAdapter:
    """Bounded public-feed parser; production eligibility remains privately gated.

    Product and variant fields must be explicit. No identifier is derived from SKU,
    handle or URL. Missing condition/availability evidence is excluded for review.
    No images or remote requests are performed by this parser.
    """

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, DOMAIN)
        if urlsplit(source_url).path != urlsplit(listing["url"]).path:
            raise CollectionBlocked("Detail product mismatch")
        parser = ProductScripts()
        parser.feed(body)
        matches = []
        for script in parser.scripts:
            try:
                payload = json.loads(script)
            except ValueError:
                continue
            nodes = payload if isinstance(payload, list) else [payload]
            for node in nodes:
                if not isinstance(node, dict) or node.get("@type") != "Product":
                    continue
                if node.get("url") != source_url:
                    continue
                offers = node.get("offers", [])
                offers = offers if isinstance(offers, list) else [offers]
                if not any(isinstance(offer, dict) and offer.get("url") == listing["url"] for offer in offers):
                    continue
                codes = {node[key] for key in ("gtin", "gtin12", "gtin13", "gtin14") if isinstance(node.get(key), str)}
                matches.extend(codes)
        if len(set(matches)) != 1:
            return {}
        code = matches[0]
        kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(code))
        if kind is None or not code.isascii() or not code.isdigit():
            return {}
        return {"identifier_raw": code, "identifier_type": kind, "identifier_source_url": source_url}

    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url, DOMAIN)
        payload = json.loads(body)
        if set(payload) != {"products"} or not isinstance(payload["products"], list):
            raise CollectionBlocked("Public product feed contract changed")
        listings, exclusions = [], []
        for product in payload["products"]:
            handle = product.get("handle")
            if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", handle):
                raise CollectionBlocked("Invalid product handle")
            product_url = f"https://{DOMAIN}/products/{handle}"
            tags = product.get("tags", [])
            if isinstance(tags, str):
                tags = tags.split(",")
            evidence = " ".join([str(product.get("product_type", "")), str(product.get("title", "")),
                                 text(product.get("body_html")), " ".join(map(str, tags))]).lower()
            used = bool(re.search(r"\b(used|pre[- ]?owned|second[- ]hand|vintage|graded|vg\+?|nm|mint condition)\b", evidence))
            explicit_new = str(product.get("product_type", "")).strip().lower() == "new" or any(str(tag).strip().lower() in {"new", "new vinyl", "new records", "condition:new"} for tag in tags)
            vinyl = bool(re.search(r"\b(vinyl|lp|12 inch|7 inch)\b", evidence))
            nonvinyl = bool(re.search(r"\b(cd|sacd|cassette|dvd|blu[- ]?ray|merchandise|t[- ]shirt)\b", evidence))
            if used or not explicit_new or not vinyl or nonvinyl:
                exclusions.append({"url": product_url, "signal": "used" if used else "new_vinyl_not_proven", "at": observed_at})
                continue
            variants = product.get("variants")
            if not isinstance(variants, list) or not variants:
                exclusions.append({"url": product_url, "signal": "variant_not_proven", "at": observed_at})
                continue
            for variant in variants:
                if type(variant.get("available")) is not bool or not variant.get("id"):
                    exclusions.append({"url": product_url, "signal": "availability_not_proven", "at": observed_at})
                    continue
                title = str(product.get("title") or "")
                split = re.split(r"\s[|–—-]\s", title, maxsplit=1)
                if len(split) != 2:
                    exclusions.append({"url": product_url, "signal": "artist_title_review_required", "at": observed_at})
                    continue
                price = decimal_price(variant.get("price"))
                base_raw = variant.get("compare_at_price")
                base = decimal_price(base_raw) if base_raw else price
                if Decimal(base) < Decimal(price):
                    raise CollectionBlocked("Base price below sale price")
                code = variant.get("barcode")
                # Missing raw barcode remains unpublishable; detail may provide an explicit barcode later.
                kind = {12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}.get(len(code), "unknown") if isinstance(code, str) else "unknown"
                listings.append({"url": f"{product_url}?variant={variant['id']}", "artist": split[0], "title": split[1],
                                 "identifier_raw": code, "identifier_type": kind, "identifier_source_url": source_url,
                                 "price": price, "base_price": base, "sale_price": price if Decimal(price) < Decimal(base) else None,
                                 "currency": "USD", "availability": "in_stock" if variant["available"] else "out_of_stock",
                                 "observed_at": observed_at, "price_source_url": source_url, "price_source": "listing",
                                 "availability_source": "listing", "product_type": "vinyl", "condition": "new",
                                 "condition_source_url": source_url,
                                 "price_context": {"vat": "unknown", "kind": "public", "variant": str(variant["id"]),
                                                   "buyable_variant": True, "units": 1, "bundle": False, "membership": False,
                                                   "mandatory_surcharge": "0", "from_price": False},
                                 "source_fragment": json.dumps({"title": title, "tags": tags,
                                                                 "variant": {key: variant.get(key) for key in ('id', 'price', 'compare_at_price', 'available', 'barcode')}})})
        next_url = None
        if payload["products"]:
            parsed = urlsplit(source_url)
            query = parse_qs(parsed.query)
            query["page"] = [str(int(query.get("page", ["1"])[0]) + 1)]
            next_url = urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))
        return ListingPage(tuple(listings), next_url, tuple(exclusions))
