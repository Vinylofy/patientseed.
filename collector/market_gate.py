"""Evidence-based market eligibility for scraper admission.

The factory must not infer a shop's delivery market from its TLD, currency, or
language.  A profile needs an explicitly sourced origin country and an
explicitly sourced destination policy before it can be admitted.
"""
from __future__ import annotations

import re


TARGET_MARKETS = ("NL",)
_CODE = re.compile(r"^[A-Z]{2}$")


def _codes(value):
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item).strip().upper() for item in value if _CODE.fullmatch(str(item).strip().upper())})


def assess(profile, *, target_markets=TARGET_MARKETS):
    """Return a durable market decision without making a network request.

    ``UNKNOWN_REVIEW`` is intentionally distinct from ``NOT_ELIGIBLE``:
    missing evidence is a review queue item, not a rejection of the shop.
    """
    origin = str(profile.get("country") or "").strip().upper()
    targets = _codes(profile.get("target_markets")) or _codes(target_markets)
    shipping_value = profile.get("shipping_countries")
    shipping = _codes(shipping_value)
    shipping_status = str(profile.get("shipping_status") or "").strip().lower()
    result = {
        "status": "UNKNOWN_REVIEW",
        "target_markets": targets,
        "origin_country": origin or None,
        "origin_source": profile.get("country_source"),
        "shipping_countries": shipping,
        "shipping_source": profile.get("shipping_source"),
    }
    if not _CODE.fullmatch(origin):
        result["reason"] = "origin_country_missing_or_invalid"
        return result
    if shipping_status in {"worldwide", "all", "all_countries", "eu_and_worldwide"}:
        result.update(status="ELIGIBLE", reason="explicit_worldwide_shipping_policy")
        return result
    if shipping_value is None or not shipping:
        result["reason"] = "shipping_destinations_missing_or_unproven"
        return result
    if any(target in shipping for target in targets):
        result.update(status="ELIGIBLE", reason="target_market_in_explicit_shipping_destinations")
    else:
        result.update(status="NOT_ELIGIBLE", reason="target_market_not_in_explicit_shipping_destinations")
    return result
