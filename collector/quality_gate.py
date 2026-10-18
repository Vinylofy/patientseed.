"""Bounded release validation; no database, tokens, imports or production writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from collector.build_scrapers import source_module
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.execute_generated import load_profile, parse_listing
from collector.price_quality import assess
from collector.recon import valid_gtin
from collector.transport import Transport, public_source


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(path):
    profile = json.loads(path.read_text())
    adapter = Path(source_module(profile['platform']).replace('.', '/') + '.py')
    return hashlib.sha256(b'\0'.join(p.read_bytes() for p in (path, path.with_suffix('.py'), adapter))).hexdigest()


class ProductJson(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.parts = []; self.nodes = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type') == 'application/ld+json':
            self.active = True; self.parts = []
    def handle_data(self, data):
        if self.active: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.active = False
            try: self.nodes.extend(products(json.loads(''.join(self.parts))))
            except ValueError: pass


def products(value):
    if isinstance(value, list):
        return [node for child in value for node in products(child)]
    if not isinstance(value, dict): return []
    types = value.get('@type', [])
    if isinstance(types, str): types = [types]
    return ([value] if 'Product' in types else []) + products(value.get('@graph', []))


def same_product(left, right):
    a, b = urlsplit(left), urlsplit(right)
    return (a.hostname or '').removeprefix('www.') == (b.hostname or '').removeprefix('www.') and a.path.rstrip('/') == b.path.rstrip('/')


def detail_evidence(html, listing):
    """Require own-product offers, matching variant where specified; never shipping."""
    parser = ProductJson(); parser.feed(html)
    codes, offers = set(), set()
    variant = parse_qs(urlsplit(listing['url']).query).get('variant', [None])[0]
    for product in parser.nodes:
        product_url = product.get('url') or str(product.get('@id', '')).split('#')[0]
        if not product_url or not same_product(product_url, listing['url']): continue
        label = str(product.get('name', ''))
        condition = str(product.get('itemCondition', ''))
        if 'UsedCondition' in condition or re.search(r'\b(?:used|pre[- ]?owned|second[- ]hand)\b', label, re.I):
            raise CollectionBlocked('detail_secondhand_signal')
        product_offers = product.get('offers', [])
        if isinstance(product_offers, dict): product_offers = [product_offers]
        matching = []
        for offer in product_offers:
            if not isinstance(offer, dict): continue
            offer_url = offer.get('url') or product_url
            if not same_product(offer_url, listing['url']): continue
            offer_variant = parse_qs(urlsplit(offer_url).query).get('variant', [None])[0]
            if variant and offer_variant != variant:
                # A single offer without a variant URL cannot prove a selected variant.
                continue
            if 'UsedCondition' in str(offer.get('itemCondition', '')):
                raise CollectionBlocked('detail_secondhand_signal')
            matching.append(offer)
        for offer in matching:
            try:
                value = Decimal(str(offer['price']))
                currency = offer['priceCurrency']
                if not value.is_finite() or value <= 0 or not isinstance(currency, str): continue
                offers.add((value, currency.upper()))
            except (KeyError, InvalidOperation): continue
            for field in ('gtin', 'gtin12', 'gtin13', 'gtin14'):
                if offer.get(field): codes.add(str(offer[field]))
        # Product-level GTIN may be ambiguous for multiple variants. The listing
        # barcode and adapter are cross-checked below; never guess from related cards.
        if matching:
            for field in ('gtin', 'gtin12', 'gtin13', 'gtin14'):
                if product.get(field): codes.add(str(product[field]))
    expected = (Decimal(str(listing['price'])), str(listing.get('currency', '')).upper())
    if offers != {expected}: raise CollectionBlocked('detail_price_currency_not_proven_or_mismatch')
    if any(not valid_gtin(code) for code in codes): raise CollectionBlocked('invalid_detail_gtin')
    normalized = {code.zfill(14) for code in codes}
    if len(normalized) > 1: raise CollectionBlocked('conflicting_detail_gtins')
    return normalized


def validate(path, *, route=None, transport_factory=Transport):
    assert_credential_free_environment()
    profile, scraper = load_profile(path)
    domain = profile['domain']; route = route or profile['catalog_route']
    public_source(route, domain)
    transport = transport_factory(domain, Limits(max_pages=1, max_requests=4, max_products=20,
        timeout_seconds=12, max_runtime_seconds=90, delay_seconds=1.0))
    evidence = {'domain': domain, 'route': route, 'observed_at': now(), 'requests': [],
                'listing_records': 0, 'detail_checked': 0, 'valid_eans': 0, 'details': [], 'database_write': False}
    def get(url):
        body = transport.get(url)
        evidence['requests'].append({'url': url, 'sha256': hashlib.sha256(body.encode()).hexdigest()})
        return body
    try:
        page = parse_listing(scraper, get(route), route, evidence['observed_at'])
        rows = list(page.listings)[:20]
        evidence['listing_records'] = len(rows)
        if not rows: raise CollectionBlocked('no_new_vinyl_records')
        if any(r.get('condition') != 'new' or r.get('product_type') != 'vinyl' for r in rows):
            raise CollectionBlocked('new_vinyl_contract_failed')
        quality = assess(rows); evidence['price_quality'] = quality
        if quality['status'] != 'pass': raise CollectionBlocked(','.join(quality['flags']))
        # Spread the sample over distinct products, not three variants of one record.
        unique = {}; chosen = []
        for row in rows: unique.setdefault(urlsplit(row['url']).path, row)
        values = list(unique.values())
        for index in sorted({0, len(values)//2, len(values)-1}): chosen.append(values[index])
        for row in chosen:
            public_source(row['url'], domain)
            html = get(row['url'])
            codes = detail_evidence(html, row)
            detail = scraper.parse_detail(html, source_url=row['url'], listing=row)
            code = detail.get('identifier_raw')
            listing_code = row.get('identifier_raw')
            for observed in (code, listing_code):
                if observed and not valid_gtin(observed): raise CollectionBlocked('invalid_gtin')
                if observed and codes and observed.zfill(14) not in codes:
                    raise CollectionBlocked('listing_detail_gtin_mismatch')
            if code and listing_code and code.zfill(14) != listing_code.zfill(14):
                raise CollectionBlocked('listing_detail_gtin_mismatch')
            # Require independent own-product detail evidence for an accepted barcode.
            accepted = code.zfill(14) if code and code.zfill(14) in codes else None
            evidence['details'].append({'url': row['url'], 'price': row['price'],
                'currency': row['currency'], 'ean': accepted, 'condition': 'new'})
            evidence['detail_checked'] += 1
            evidence['valid_eans'] += bool(accepted)
        if not evidence['valid_eans']: raise CollectionBlocked('detail_ean_not_proven')
        evidence['status'] = 'APPROVED'
    except Exception as exc:
        reason = str(exc)[:250]
        evidence.update(status='REVIEW', reason=reason, error_type=type(exc).__name__)
        if re.search(r'HTTP_(?:401|403|429)\b', reason): evidence['status'] = 'BLOCKED'
    return evidence


def health_records(root, slug):
    return {mode: json.loads(p.read_text()) for mode in ('price', 'ean')
            if (p := root / 'health' / mode / f'{slug}.json').exists()}


def approved(root, profiles, mode=None):
    state = json.loads((root / 'state.json').read_text())
    result = []
    for path in sorted(profiles.glob('*.json')):
        record = state.get('shops', {}).get(path.stem, {})
        if (not (record.get('status') == 'APPROVED' or record.get('admitted'))
                or record.get('status') == 'BLOCKED' or record.get('fingerprint') != fingerprint(path)): continue
        health = health_records(root, path.stem)
        relevant = [health[mode]] if mode in health else list(health.values()) if mode is None else []
        if any(h.get('status') in {'REPAIR_REQUIRED', 'FROZEN'} for h in relevant): continue
        result.append(path.stem)
    return result


def run_batch(profiles, root, *, limit=25, run_id='local', validator=validate, seconds=2400):
    assert_credential_free_environment()
    if not 1 <= limit <= 25: raise ValueError('quality batch limit must be 1..25')
    state_path = root / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'schema_version': 1, 'batch': 0, 'shops': {}}
    state['batch'] += 1; batch = state['batch']; started = time.monotonic(); processed = []
    candidates = []
    for path in sorted(profiles.glob('*.json')):
        previous = state['shops'].get(path.stem, {}); digest = fingerprint(path)
        health = health_records(root, path.stem)
        needs_repair = any(h.get('status') == 'REPAIR_REQUIRED' for h in health.values())
        if previous.get('fingerprint') == digest and (previous.get('status') == 'BLOCKED' or (previous.get('status') == 'FROZEN' and not needs_repair)): continue
        if previous.get('status') == 'APPROVED' and previous.get('fingerprint') == digest and not needs_repair: continue
        priority = 0 if needs_repair else 1 if not previous else 2
        candidates.append((priority, path, digest, previous, health))
    candidates.sort(key=lambda x: (x[0], x[1].stem))
    for _, path, digest, previous, health in candidates[:limit]:
        if time.monotonic() - started > seconds: break
        repair_modes = sorted(mode for mode, h in health.items() if h.get('status') == 'REPAIR_REQUIRED')
        new_cycle = repair_modes and repair_modes != previous.get('repair_modes', [])
        repairs = 0 if previous.get('status') == 'APPROVED' or new_cycle else int(previous.get('repair_attempts', 0))
        if previous.get('fingerprint') != digest: previous = {}; repairs = 0
        if previous: repairs += 1
        if repairs > 3: continue
        profile = json.loads(path.read_text())
        routes = list(dict.fromkeys([profile['catalog_route']] + [x['route'] for x in profile.get('method_candidates', [])
            if x.get('platform') == profile['platform'] and x.get('status') == 'ADAPTER_PARSED']))
        route = routes[min(repairs, len(routes)-1)]
        try:
            result = validator(path, route=route)
        except Exception as exc:
            result = {'status': 'REVIEW', 'reason': str(exc)[:250], 'error_type': type(exc).__name__}

        status = result['status']
        if status == 'REVIEW' and repairs >= 3: status = 'FROZEN'
        record = {'fingerprint': digest, 'domain': profile['domain'], 'batch': batch,
            'repair_attempts': repairs, 'repair_modes': repair_modes,
            'admitted': status == 'APPROVED' or previous.get('status') == 'APPROVED' or bool(previous.get('admitted')),
            'status': status, 'run_id': run_id,
            'updated_at': now(), 'evidence': result, 'history': previous.get('history', []) +
            [{'batch': batch, 'status': status, 'reason': result.get('reason'), 'run_id': run_id}]}
        state['shops'][path.stem] = record
        if previous.get('approved_route'): record['approved_route'] = previous['approved_route']
        if previous.get('admission_evidence'): record['admission_evidence'] = previous['admission_evidence']
        if status == 'APPROVED': record['admission_evidence'] = result
        if status == 'FROZEN' and record['admitted']:
            for mode in repair_modes:
                p = root / 'health' / mode / path.name
                h = json.loads(p.read_text()); h.update(status='FROZEN', repair_attempts=repairs, last_quality_check_at=now())
                p.write_text(json.dumps(h, indent=2)+'\n')
        if status == 'APPROVED' and route != profile['catalog_route']:
            # Route override is part of the admitted release, not a silent parser edit.
            record['approved_route'] = route
        if status == 'APPROVED':
            for mode in ('price', 'ean'):
                p = root / 'health' / mode / path.name; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({'status': 'ACTIVE', 'consecutive_failures': 0,
                    'repair_attempts': 0, 'last_known_good': now(), 'last_good_run_id': run_id,
                    'last_evidence': 'bounded_quality_gate', 'last_quality_check_at': now(), 'domain': profile['domain']}, indent=2)+'\n')
        if status == 'FROZEN':
            directory = root / 'frozen' / path.stem; directory.mkdir(parents=True, exist_ok=True)
            for source in (path, path.with_suffix('.py')): (directory / source.name).write_bytes(source.read_bytes())
            (directory / 'status.json').write_text(json.dumps(record, indent=2)+'\n')
        root.mkdir(parents=True, exist_ok=True)
        state['updated_at'] = now(); state['last_run_id'] = run_id
        state_path.write_text(json.dumps(state, indent=2)+'\n')  # Checkpoint after every shop.
        processed.append({'slug': path.stem, 'status': status, 'reason': result.get('reason')})
        print(json.dumps(processed[-1]), flush=True)
    return {'batch': batch, 'processed': processed, 'remaining': len(candidates)-len(processed), 'database_write': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--run-id', default='local')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--mode', choices=('price', 'ean'))
    args = parser.parse_args()
    if args.plan:
        names = approved(args.state_root, args.profiles, args.mode)
        print(json.dumps([{'slugs': names[i:i+100]} for i in range(0,len(names),100)]))
    else:
        result = run_batch(args.profiles, args.state_root, limit=args.limit, run_id=args.run_id)
        print(json.dumps(result))
        Path('quality-batch-result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__ == '__main__': main()
