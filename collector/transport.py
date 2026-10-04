from __future__ import annotations

import ipaddress
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from collector.contracts import CollectionBlocked, Limits


def public_source(url: str, domain: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443) or host != domain.removeprefix("www.").lower()
                or "." not in host or host.endswith((".local", ".internal", ".localhost"))):
            raise CollectionBlocked("Unapproved public source")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return url
    except (TypeError, ValueError) as exc:
        raise CollectionBlocked("Invalid public source") from exc
    raise CollectionBlocked("IP destinations are not allowed")


class SameShopRedirects(HTTPRedirectHandler):
    def __init__(self, domain: str):
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_source(newurl, self.domain)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Transport:
    """Bounded HTTPS transport; TLS validation and platform proxy remain enabled."""

    def __init__(self, domain: str, limits: Limits):
        self.domain, self.limits = domain, limits
        self.started, self.last_request, self.requests = time.monotonic(), None, 0
        self.opener = build_opener(SameShopRedirects(domain))

    def get(self, url: str) -> str:
        public_source(url, self.domain)
        if self.requests >= self.limits.max_requests:
            raise CollectionBlocked("Request budget exhausted")
        if self.last_request is not None:
            delay = self.limits.delay_seconds - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
        if time.monotonic() - self.started >= self.limits.max_runtime_seconds:
            raise CollectionBlocked("Runtime budget exhausted")
        self.requests += 1
        self.last_request = time.monotonic()
        request = Request(url, headers={"User-Agent": "PublicCatalogCollector/0.1"})
        try:
            with self.opener.open(request, timeout=self.limits.timeout_seconds) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise CollectionBlocked("Response size limit")
                return raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except HTTPError as exc:
            # Conservative: no retry of a blocked site, login or rate-limit response.
            raise CollectionBlocked(f"HTTP_{exc.code}") from exc
