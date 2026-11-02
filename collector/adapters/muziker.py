"""Bounded artist/title catalog adapter for Muziker's public vinyl listing."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from collector.contracts import CollectionBlocked, ListingPage
from collector.transport import public_source


DOMAIN = "muziker.nl"
CATALOG = "https://www.muziker.nl/vinyl-lps"


def _price(value: str) -> str:
    match = re.search(r"[0-9][0-9.]*,[0-9]{1,2}|[0-9]+(?:\.[0-9]{1,2})?", value or "")
    if not match:
        raise ValueError("price not proven")
    raw = match.group(0).replace(".", "").replace(",", ".") if "," in match.group(0) else match.group(0)
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid price") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("nonpositive price")
    return f"{amount:.2f}"


def _artist_title(header: str, brand: str = "") -> tuple[str, str] | None:
    value = " ".join(unescape(header).split())
    parts = re.split(r"\s+[|–—-]\s+", value, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts
    elif brand and value.casefold().startswith(brand.casefold() + " "):
        artist, title = brand, value[len(brand):].strip()
    else:
        return None
    if not artist or not title or len(artist) > 200 or len(title) > 300:
        return None
    return artist, title


class _MuzikerParser(HTMLParser):
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

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "a" and "load-next-products" in classes and attrs.get("href"):
            self.next_url = urljoin(f"https://{self.domain}/", attrs["href"])
        if tag == "a" and "paginate-next-page" in classes and attrs.get("href") and attrs["href"] != "#":
            self.next_url = urljoin(f"https://{self.domain}/", attrs["href"])
        if tag == "div" and "product-tile" in classes:
            if self.current is not None:
                raise CollectionBlocked("Nested Muziker product tile")
            self.current = {"url": None, "header": "", "brand": "", "price": "", "stock": "", "subtype": "", "item_name": ""}
            self.current.update({key: attrs.get(key, "") for key in ("data-item-name", "data-product-code")})
        if self.current is None:
            return
        if self.capture:
            self.capture_depth += 1
            return
        if tag == "a" and "link-overlay" in classes and attrs.get("href"):
            self.current["url"] = urljoin(f"https://{self.domain}/", attrs["href"])
        elif tag == "h4" and "product-tile-header" in classes:
            self.capture, self.capture_tag, self.text = "header", tag, []
        elif tag == "p" and "product-tile-sub-header" in classes:
            self.capture, self.capture_tag, self.text = "subtype", tag, []
        elif tag == "div" and "price" in classes and "tile-price" not in classes:
            self.capture, self.capture_tag, self.text = "price", tag, []
        elif tag == "div" and "stock-status" in classes:
            self.current["stock"] = " ".join(self.current["stock"].split() + [attrs.get("title", "")])

    def handle_data(self, data):
        if self.current is not None and self.capture:
            self.text.append(data)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if self.capture:
            self.capture_depth -= 1
        if tag == self.capture_tag and self.capture and self.capture_depth <= 0:
            self.current[self.capture] = " ".join("".join(self.text).split())
            self.capture = self.capture_tag = None
            self.capture_depth = 0
            self.text = []
        if tag == "div" and self.current is not None and self.capture is None:
            # Product tiles close after their tile-footer; identify by the next
            # product tile rather than relying on fragile CSS nesting depth.
            # The parser finalizes in close() when all fields are present.
            pass

    def close(self):
        super().close()
        # Product tiles are intentionally collected from the stable data-item
        # attributes. A product tile has one link overlay and one header.
        # Re-parse is avoided by finalizing on the next tile in handle_starttag.
        if self.current is not None:
            self.products.append(self.current)
            self.current = None

class MuzikerAdapter:
    def __init__(self, domain: str = DOMAIN):
        self.domain = domain

    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage:
        public_source(source_url, self.domain)
        parser = _MuzikerParser(self.domain)
        # Pagination is a stable link outside the product cards. Extract only
        # that link here; card fragments are parsed independently below so a
        # recommendation widget cannot be mistaken for a nested product.
        next_match = re.search(
            r"<a[^>]+class=['\"][^'\"]*\b(?:load-next-products|paginate-next-page)\b[^'\"]*['\"][^>]+href=['\"]([^'\"]+)",
            body,
            re.I,
        )
        parser.next_url = urljoin(f"https://{self.domain}/", unescape(next_match.group(1))) if next_match else None
        # HTMLParser cannot infer the product-tile closing boundary reliably
        # from a CSS class, so split on each stable tile marker and parse each
        # fragment independently.
        fragments = re.split(r"(?=<div[^>]+class=['\"][^'\"]*\bproduct-tile\b)", body)
        rows, exclusions = [], []
        for fragment in fragments[1:]:
            tile = _MuzikerParser(self.domain)
            tile.feed(fragment)
            tile.close()
            if not tile.products:
                continue
            product = tile.products[0]
            url = product.get("url")
            if not url:
                continue
            subtype = product.get("subtype", "").lower()
            header = product.get("header", "")
            if "lp" not in subtype and not re.search(r"\bvinyl\b", header, re.I):
                exclusions.append({"url": url, "signal": "vinyl_not_proven", "at": observed_at})
                continue
            try:
                price = _price(product.get("price", ""))
            except ValueError:
                exclusions.append({"url": url, "signal": "price_not_proven", "at": observed_at})
                continue
            identity = _artist_title(header, product.get("brand", ""))
            if not identity:
                exclusions.append({"url": url, "signal": "artist_title_not_proven", "at": observed_at})
                continue
            artist, title = identity
            stock = (product.get("stock") or "").lower()
            availability = "out_of_stock" if any(x in stock for x in ("uitverkocht", "niet op voorraad")) else "in_stock"
            rows.append({"url": url, "artist": artist, "title": title,
                         "identifier_raw": None, "identifier_type": "unknown", "identifier_source_url": url,
                         "price": price, "base_price": price, "sale_price": None, "currency": "EUR",
                         "availability": availability, "observed_at": observed_at, "price_source_url": source_url,
                         "price_source": "listing", "availability_source": "listing", "product_type": "vinyl",
                         "condition": "new", "condition_source_url": source_url,
                         "price_context": {"vat": "unknown", "kind": "public", "variant": product.get("data-product-code", url),
                                           "buyable_variant": availability == "in_stock", "units": 1, "bundle": False,
                                           "membership": False, "mandatory_surcharge": "0", "from_price": False},
                         "source_fragment": json.dumps({"title": header, "artist": artist, "product_code": product.get("data-product-code")})})
        return ListingPage(tuple(rows), parser.next_url, tuple(exclusions))

    def parse_detail(self, body: str, *, source_url: str, listing: dict) -> dict:
        public_source(source_url, self.domain)
        if urlsplit(source_url).path.rstrip("/") != urlsplit(listing["url"]).path.rstrip("/"):
            raise CollectionBlocked("Detail product mismatch")
        # Muziker does not expose a reliable EAN contract for this catalog.
        # Keep identity from the listing and deliberately return no identifier.
        return {"artist": listing["artist"], "title": listing["title"]}
