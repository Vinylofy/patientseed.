"""Artist/title identity overlay; never guesses barcodes or changes listing prices."""
from __future__ import annotations
from dataclasses import replace
import json
import re
from urllib.parse import urlsplit

INVALID = {'artist', 'title', 'unknown', 'vinyl', 'lp', 'new', 'nieuw', 'used', 'cd', 'sealed'}


def clean(value):
    return re.sub(r'\s+', ' ', value).strip() if isinstance(value, str) else ''


def pair(artist, title):
    artist, title = clean(artist), clean(title)
    if (not artist or not title or len(artist) > 200 or len(title) > 300
            or artist.casefold() in INVALID or title.casefold() in INVALID
            or any(c in artist+title for c in '<>\r\n')):
        return None
    return {'artist': artist, 'title': title}


def identity(row, raw=None):
    raw = raw or {}
    explicit = []
    for attribute in raw.get('attributes', []) if isinstance(raw.get('attributes'), list) else []:
        if not isinstance(attribute, dict) or clean(attribute.get('name')).casefold() not in {'artist', 'artiest', 'interpret'}:
            continue
        terms = attribute.get('terms', [])
        explicit += [clean(t.get('name')) for t in terms if isinstance(t, dict) and clean(t.get('name'))]
    name = raw.get('title') or raw.get('name')
    if not name:
        try:
            fragment = json.loads(row.get('source_fragment', '{}'))
            name = fragment.get('title') or fragment.get('name')
        except (ValueError, TypeError):
            pass
    if not name:
        name = (clean(row.get('artist'))+' - '+clean(row.get('title'))) if row.get('artist') else row.get('title')
    name = clean(name)
    pieces = re.split(r'\s[|–—-]\s', name)
    if len(set(explicit)) == 1:
        artist = explicit[0]
        title = pieces[1] if len(pieces) == 2 and pieces[0].casefold() == artist.casefold() else name
        found = pair(artist, title)
        if found:
            return dict(found, method='explicit_product_artist_attribute')
    if len(pieces) != 2:
        return None
    found = pair(*pieces)
    return dict(found, method='consistent_single_delimiter') if found else None


def raw_products(body, platform):
    try:
        data = json.loads(body)
    except ValueError:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        value = data.get('products', data.get('data', []))
        return value if isinstance(value, list) else []
    return []


def enrich(rows, body, platform):
    raw = raw_products(body, platform)
    result = []
    for row in rows:
        path = urlsplit(row['url']).path.rstrip('/')
        product = next((p for p in raw if isinstance(p, dict) and
            ((p.get('permalink') and urlsplit(p['permalink']).path.rstrip('/') == path)
             or (p.get('handle') and path == '/products/'+str(p['handle'])))), {})
        found = identity(row, product)
        result.append({**row, **({k: found[k] for k in ('artist','title')} if found else {}),
                       'identity_method': found['method'] if found else None})
    return result


class ArtistTitleAdapter:
    def __init__(self, adapter, platform):
        self.adapter, self.platform = adapter, platform

    def parse_listing(self, body, *, source_url, observed_at):
        page = self.adapter.parse_listing(body, source_url=source_url, observed_at=observed_at)
        return replace(page, listings=tuple(row for row in enrich(page.listings, body, self.platform)
                                          if row.get('identity_method')))

    def parse_detail(self, body, *, source_url, listing):
        # Future matching remains outside this public collector. No canonical IDs.
        return {'artist': listing['artist'], 'title': listing['title']}
