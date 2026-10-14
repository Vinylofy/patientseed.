"""Quality checks for listing prices before they enter health status."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


SHIPPING_TERMS = re.compile(
    r"\b(?:shipping|ship(?:ping)?|postage|freight|delivery|handling|verzend(?:ing)?|porto|versand)\b",
    re.IGNORECASE,
)


def assess(records: list[dict]) -> dict:
    flags: list[str] = []
    prices: list[Decimal] = []
    currencies = set()
    shipping_hits = 0
    for record in records:
        raw = record.get("price")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            flags.append("price_not_numeric")
            continue
        if value <= 0:
            flags.append("price_not_positive")
        prices.append(value)
        if record.get("currency"):
            currencies.add(record["currency"])
        text = " ".join(str(record.get(key, "")) for key in ("title", "artist", "source_fragment"))
        if SHIPPING_TERMS.search(text):
            shipping_hits += 1
    if len(currencies) > 1:
        flags.append("mixed_currency")
    if shipping_hits:
        flags.append("shipping_term_in_product_identity")
    # A small vinyl selection can legitimately share a price. Only flag a
    # completely uniform sample once at least twenty products were checked.
    if len(prices) >= 20 and len(set(prices)) == 1:
        flags.append("uniform_price_suspicious")
    unique_flags = list(dict.fromkeys(flags))
    return {"status": "pass" if not unique_flags else "review",
            "flags": unique_flags, "records_checked": len(records),
            "unique_prices": len(set(prices)), "shipping_hits": shipping_hits,
            "currencies": sorted(currencies)}
