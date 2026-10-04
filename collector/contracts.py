from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class CollectionBlocked(ValueError):
    pass


def assert_credential_free_environment() -> None:
    forbidden = ("DATABASE", "SUPABASE", "SERVICE_ROLE", "DEPLOY", "MODEL_API", "OPENAI", "ANTHROPIC",
                 "GH_TOKEN", "GITHUB_TOKEN", "AWS_ACCESS_KEY", "AWS_SECRET", "AZURE_CLIENT_SECRET")
    for name in os.environ:
        if any(marker in name.upper() for marker in forbidden) and os.environ.get(name):
            raise CollectionBlocked("Credential-bearing execution environment is not allowed")


@dataclass(frozen=True)
class Limits:
    max_pages: int = 3
    max_requests: int = 20
    max_products: int = 20
    timeout_seconds: int = 15
    max_runtime_seconds: int = 120
    delay_seconds: float = 1.0

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in (
            self.max_pages, self.max_requests, self.max_products,
            self.timeout_seconds, self.max_runtime_seconds,
        )) or self.delay_seconds < 0.5:
            raise CollectionBlocked("Invalid collection bounds")


@dataclass(frozen=True)
class ListingPage:
    listings: tuple[dict, ...]
    next_url: str | None
    # Minimal exclusion provenance; never keep a used product payload.
    exclusions: tuple[dict, ...] = ()


class Adapter(Protocol):
    def parse_listing(self, body: str, *, source_url: str, observed_at: str) -> ListingPage: ...


def merge_detail(listing: dict, detail: dict) -> dict:
    allowed = {"identifier_raw", "identifier_type", "identifier_source_url", "artist", "title"}
    return {**listing, **{key: value for key, value in detail.items() if key in allowed and value}}
