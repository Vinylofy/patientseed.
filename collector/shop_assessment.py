"""Versioned EAN/ARTIST_TITLE suitability, independent of production admission."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from dataclasses import replace
from collector.assessment_robots import allowed, rules

from collector.artist_title import enrich
from collector.contracts import CollectionBlocked, Limits, assert_credential_free_environment
from collector.price_quality import assess as price_quality
from collector.quality_gate import ProductJson, detail_evidence, same_product
from collector.recon import ADAPTERS, probe, shopify_currency
from collector.transport import Transport

VERSION = 2
REVISION = "2.1"
LIMITS = Limits(max_pages=2, max_requests=16, max_products=20, timeout_seconds=10,
                max_runtime_seconds=180, delay_seconds=1)


def now():
    return datetime.now(timezone.utc).isoformat()


def classify(e):
    """Unknown evidence never becomes a positive claim, nor a final rejection."""
    if e.get('existing_ean_approved'):
        return 'EAN', ['existing_ean_admission_retained']
    if e.get('secondhand_only') is True:
        return 'UNSUITABLE', ['secondhand_only']
    if e.get('active') is False:
        return 'UNSUITABLE', ['no_public_catalogue']
    if e.get('access_problem'):
        return 'MANUAL_REVIEW', [e['access_problem']]
    required = ('vinyl', 'new_used_distinguishable', 'public_prices', 'availability', 'stable_urls')
    missing = [key for key in required if e.get(key) is not True]
    if missing:
        return 'MANUAL_REVIEW', ['not_proven:'+key for key in missing]
    checked = e.get('detail_checked', 0)
    if checked < 3 or e.get('detail_price_proven') != checked:
        return 'MANUAL_REVIEW', ['insufficient_representative_product_evidence']
    if e.get('ean_valid', 0) >= math.ceil(checked*.8):
        return 'EAN', ['own_product_valid_gtin_coverage_at_least_80_percent_of_sample']
    if e.get('identity_details_proven') == checked and e.get('identity_listing_ratio', 0) >= .8:
        return 'ARTIST_TITLE', ['artist_title_consistent_on_listing_and_three_distinct_details', 'ean_coverage_insufficient']
    return 'MANUAL_REVIEW', ['artist_title_not_consistently_proven']


class EvidenceTransport:
    def __init__(self, domain, factory=Transport):
        self.domain = domain
        self.transport = factory(domain, LIMITS)
        self.cache, self.requests = {}, []
        self.robots = ''
        url = f'https://{domain}/robots.txt'
        try:
            body = self.transport.get(url)
        except CollectionBlocked as exc:
            if str(exc) != 'HTTP_404':
                raise
            body = ''
        self.robots = body
        _,delay = rules(body)
        if not math.isfinite(delay) or delay > 30:
            raise CollectionBlocked('robots_crawl_delay_exceeds_bounded_pilot')
        if delay > LIMITS.delay_seconds:
            self.transport.limits = replace(LIMITS, delay_seconds=delay)
        self.requests.append({'url': url, 'sha256': hashlib.sha256(body.encode()).hexdigest()})

    def get(self, url):
        if not allowed(self.robots, url):
            raise CollectionBlocked('robots_disallow')
        if url not in self.cache:
            self.cache[url] = self.transport.get(url)
            self.requests.append({'url': url, 'sha256': hashlib.sha256(self.cache[url].encode()).hexdigest()})
        return self.cache[url]


def own_nodes(html, url):
    parser = ProductJson(); parser.feed(html)
    return [p for p in parser.nodes if same_product(p.get('url') or str(p.get('@id','')).split('#')[0], url)]


def condition_evidence(nodes):
    values=[];texts=[]
    for node in nodes:
        values.append(str(node.get('itemCondition','')))
        texts.append(str(node.get('name',''))+' '+str(node.get('description','')))
        props=node.get('additionalProperty',[])
        if isinstance(props,dict):props=[props]
        for prop in props if isinstance(props,list) else []:
            if isinstance(prop,dict) and str(prop.get('name','')).casefold() in {'condition','media condition','sleeve condition'}:
                value=str(prop.get('value','')).casefold()
                if value not in {'new','nieuw','sealed','mint (new)'}:
                    return 'ambiguous_explicit_condition'
        offers=node.get('offers',[])
        if isinstance(offers,dict):offers=[offers]
        values += [str(o.get('itemCondition','')) for o in offers if isinstance(o,dict)]
    if any('UsedCondition' in value for value in values) or any(re.search(
        r'\b(?:second[- ]?hand|pre[- ]?owned|tweedehands|2e\s*hands|gebraucht|media\s+condition|sleeve\s+condition)\b',text,re.I) for text in texts):
        return 'used_or_grading_signal'
    if any(value and 'NewCondition' not in value for value in values):
        return 'ambiguous_explicit_condition'
    return 'explicit_new' if any('NewCondition' in value for value in values) else 'existing_no_used_signal_policy'


def identity_on_detail(row,nodes):
    if not row.get('identity_method'):return False
    for node in nodes:
        named=node.get('byArtist') or node.get('artist')
        if isinstance(named,dict):named=named.get('name')
        if named and (not isinstance(named,str) or named.casefold()!=row['artist'].casefold()):
            continue
        name=re.sub(r'\s+',' ',str(node.get('name',''))).casefold()
        if row['title'].casefold() in name and (named or row['artist'].casefold() in name):
            return True
    return False


def assess_shop(item, *, country=None, prior=None, existing=False, existing_approved=False, transport_factory=Transport):
    assert_credential_free_environment()
    prior = prior or {}
    result = {'assessment_version': VERSION, 'assessment_revision':REVISION, 'assessed_at': now(), 'shop_id': item['domain'] or f"source-row-{item['row']}",
              'row': item['row'], 'name': item['name'], 'domain': item['domain'], 'country': country,
              'website': f"https://{item['domain']}/" if item['domain'] else None,
              'previous_status': prior.get('status'), 'previous_reason': prior.get('reason'),
              'existing_scraper': existing, 'existing_ean_approved': existing_approved,
              'product_count': None, 'product_count_basis': 'unknown_not_full_catalogue',
              'database_write': False, 'migration_approved': False, 'manual_test_required': True}
    e = {'existing_ean_approved': existing_approved, 'active': None, 'vinyl': None,
         'secondhand_only': None, 'new_used_distinguishable': None, 'public_prices': None,
         'availability': None, 'stable_urls': None, 'detail_checked': 0, 'detail_price_proven': 0,
         'ean_valid': 0, 'identity_details_proven': 0, 'identity_listing_ratio': 0,
         'sale_price_recognizable': None, 'cover_available': None}
    if existing_approved:
        result['evidence_basis'] = 'existing_unchanged_quality_admission'
    elif item['source_status'] not in {'READY','DUPLICATE_DOMAIN'} or not item['domain']:
        e['access_problem'] = 'source_identity_requires_review:'+item['source_status']
    else:
        transport = None
        try:
            transport = EvidenceTransport(item['domain'], transport_factory)
            observed = probe({**item, 'source_status': 'READY'}, lambda *_: transport)
            result['source_observation'] = observed
            result['platform'] = observed.get('platform')
            result['catalog_route'] = observed.get('source_url')
            route = observed.get('source_url')
            platform = observed.get('platform')
            if observed.get('status') == 'SOURCE_BLOCKED':
                raise CollectionBlocked(observed.get('reason', 'source_blocked'))
            if platform not in ADAPTERS or route not in transport.cache:
                raise CollectionBlocked('supported_catalogue_route_not_proven')
            adapter = ADAPTERS[platform](item['domain'])
            body = transport.cache[route]
            page = adapter.parse_listing(body, source_url=route, observed_at=result['assessed_at'])
            rows = list(page.listings)[:20]
            currency = observed.get('currency')
            if currency and platform == 'shopify':
                rows = [{**row, 'currency': currency} for row in rows]
            rows = enrich(rows, body, platform)
            result['listing_sample'] = len(rows)
            e.update(active=True, vinyl=bool(rows), stable_urls=bool(rows),
                     availability=bool(rows) and all(r.get('availability') in {'in_stock','out_of_stock','preorder'} for r in rows),
                     public_prices=bool(rows) and price_quality(rows)['status'] == 'pass')
            e['identity_listing_ratio'] = sum(bool(r.get('identity_method')) for r in rows)/len(rows) if rows else 0
            result['price_quality'] = price_quality(rows)
            # Raw used exclusions do not prove the entire store is used-only.
            result['secondhand_observed'] = any('used' in x.get('signal','') for x in page.exclusions)
            unique = list({urlsplit(r['url']).path:r for r in reversed(rows)}.values())
            selected = [unique[i] for i in sorted({0,len(unique)//2,len(unique)-1})] if unique else []
            details = []
            seen_codes = set()
            for row in selected:
                html = transport.get(row['url'])
                nodes = own_nodes(html, row['url'])
                codes = detail_evidence(html, row)
                if codes & seen_codes:
                    raise CollectionBlocked('gtin_reused_across_distinct_products')
                seen_codes.update(codes)
                e['detail_checked'] += 1
                e['detail_price_proven'] += 1
                e['ean_valid'] += bool(codes)
                identity_proven = identity_on_detail(row,nodes)
                e['identity_details_proven'] += identity_proven
                details.append({'url':row['url'], 'artist':row.get('artist'), 'title':row.get('title'),
                    'identity_method': row.get('identity_method'), 'identity_proven': identity_proven,
                    'price':row['price'], 'currency':row['currency'], 'valid_eans':sorted(codes),
                    'condition_basis':condition_evidence(nodes)})
                if any(node.get('image') for node in nodes): e['cover_available'] = True
            result['examples'] = details
            e['new_used_distinguishable'] = bool(details) and all(d['condition_basis'] in {'explicit_new','existing_no_used_signal_policy'} for d in details)
        except Exception as exc:
            e['access_problem'] = str(exc)[:180] if isinstance(exc, CollectionBlocked) else type(exc).__name__
            if transport is None:
                result['requests'] = [{'url': f"https://{item['domain']}/robots.txt", 'error': e['access_problem']}]
        if transport is not None:
            result['requests'] = transport.requests
    kind, reasons = classify(e)
    result.update(scraper_type=kind, preferred_scraper_type=kind if kind in {'EAN','ARTIST_TITLE'} else None,
                  supports_artist_title_fallback=kind=='EAN' and e['identity_details_proven']>=3,
                  suitability='SUITABLE' if kind in {'EAN','ARTIST_TITLE'} else kind,
                  assessment_ready=kind in {'EAN','ARTIST_TITLE'} and country is not None and not existing_approved,
                  build_eligible=kind in {'EAN','ARTIST_TITLE'} and not existing_approved,
                  reason=reasons, evidence=e, priority='LOW', priority_reason=['insufficient_evidence'])
    if kind in {'EAN','ARTIST_TITLE'}:
        result['priority'] = 'HIGH' if country in {'NL','BE'} else 'MEDIUM'
        result['priority_reason'] = ['country_order_NL_BE_GB_US_other', 'bounded_identity_price_quality',
                                     'reuses_existing_adapter', 'catalogue_size_unknown_not_assumed']
    if result['build_eligible'] and 'body' in locals():
        result['_listing_body'] = body
    result['non_ean_potential'] = ('UNKNOWN' if e['detail_checked'] < 3 else 'HIGH' if not e['ean_valid']
                                   else 'MEDIUM' if e['ean_valid']/e['detail_checked'] < .8 else 'LOW')
    result['potential_basis'] = 'bounded_sample_only'
    result['build_status'] = ('EXISTING_EAN_RETAINED' if existing_approved else 'READY_TO_BUILD'
                              if result['build_eligible'] else 'NOT_BUILDABLE_WITH_CURRENT_EVIDENCE')
    return result
