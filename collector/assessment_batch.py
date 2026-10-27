"""Resume the existing queue with additive version-2 shop suitability evidence."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import time

from collector.build_scrapers import build, slug
from collector.contracts import assert_credential_free_environment
from collector.execute_generated import load_profile, parse_listing
from collector.manual_run import load_queue
from collector.quality_gate import fingerprint
from collector.shop_assessment import VERSION, REVISION, assess_shop, now


INDEX_FIELDS = ('assessment_version','assessment_revision','assessment_id','assessed_at','shop_id','name','domain','website','country',
                'scraper_type','preferred_scraper_type','supports_artist_title_fallback','suitability',
                'priority','priority_reason','reason','build_status','existing_scraper','assessment_ready','candidate_ref',
                'product_count','product_count_basis','platform','non_ean_potential','potential_basis','ean_availability',
                'country_source','existing_scraper_status','example_urls')


def shops(queue, metadata):
    unique = {}
    for item in queue:
        own_domain = item['domain'] and item['source_status'] in {'READY','DUPLICATE_DOMAIN'}
        key = item['domain'].lower().removeprefix('www.') if own_domain else 'source-row-'+str(item['row'])
        if key in unique:
            unique[key]['queue_rows'].append(item['row'])
            continue
        country = metadata.get('shops',{}).get(str(item['row']),{}).get('country')
        unique[key] = {**item, 'shop_id':key, 'queue_rows':[item['row']], 'country':country,
            'country_source':metadata.get('shops',{}).get(str(item['row']),{}).get('country_source')}
    return list(unique.values())


def build_candidate(record, body, output):
    observed = record['source_observation']
    row = {**observed, 'status':'ADAPTER_TESTED', 'detail_checked':record['evidence']['detail_checked'],
           'detail_gtin_valid':record['evidence']['ean_valid'], 'scraper_type':record['scraper_type'],
           'assessment_version':VERSION, 'assessment_id':record['assessment_id'], 'country':record['country']}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = output.parent/'build-input.json'
    manifest.write_text(json.dumps({'schema_version':1,'complete':True,'results':[row]}), encoding='utf-8')
    built = build(manifest, output)
    if len(built) != 1: raise ValueError('existing builder did not accept candidate')
    profile = output/(slug(record['domain'])+'.json')
    _, scraper = load_profile(profile)
    page = parse_listing(scraper, body, record['catalog_route'], record['assessed_at'])
    if not page.listings: raise ValueError('candidate listing pilot empty')
    if record['scraper_type'] == 'ARTIST_TITLE' and any(not r.get('artist') or not r.get('title') for r in page.listings):
        raise ValueError('candidate identity incomplete')
    record.update(build_status='BUILT_AWAITING_MANUAL_TEST', build_attempts=1,
                  build_test='wrapper_import_and_live_listing_contract', build_test_records=len(page.listings),
                  candidate_ref=record['assessment_id']+'/'+profile.stem)


def run(queue, progress, index, metadata, *, published, quality, output, run_id,
        limit=100, scraper_type='AUTO', assessor=assess_shop, seconds=2400):
    assert_credential_free_environment()
    if not 1 <= limit <= len(queue) or scraper_type not in {'AUTO','EAN','ARTIST_TITLE'}:
        raise ValueError('invalid existing batch/type option')
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', run_id): raise ValueError('unsafe run identifier')
    output.mkdir(parents=True, exist_ok=True)
    assessment_id = 'v2-'+run_id
    index = deepcopy(index or {'schema_version':2,'shops':{}})
    if index['schema_version'] != VERSION: raise ValueError('unsupported assessment index')
    historical = {r['row']:r for r in progress.get('history',[])}
    historical.update({r['row']:r for r in progress.get('rechecks',[])})
    targets = shops(queue, metadata)
    states = quality.get('shops', {})
    def rank(item):
        q = states.get(slug(item['domain']), {}) if item['domain'] else {}
        missing = q.get('evidence',{}).get('reason') == 'detail_ean_not_proven'
        return ({'NL':0,'BE':1,'GB':2,'US':3}.get(item['country'],4), not missing, item['name'].casefold())
    def needs_assessment(item):
        previous=index['shops'].get(item['shop_id'],{})
        return (previous.get('assessment_revision') != REVISION or
                (previous.get('build_status') == 'READY_OTHER_SELECTED_TYPE'
                 and scraper_type in {'AUTO',previous.get('scraper_type')}))
    pending = [s for s in targets if needs_assessment(s)]
    pending.sort(key=rank)
    results = []
    start = time.monotonic()
    for item in pending[:limit]:
        if time.monotonic()-start > seconds: break
        profile = published/(slug(item['domain'])+'.json') if item['domain'] else Path('never')
        existing = profile.is_file() and profile.with_suffix('.py').is_file()
        qa = states.get(profile.stem,{})
        approved = False
        if existing and qa.get('status') != 'BLOCKED' and (qa.get('status') == 'APPROVED' or qa.get('admitted')):
            approved = qa.get('fingerprint') == fingerprint(profile)
        prior = historical.get(item['row'], {})
        try:
            old=index['shops'].get(item['shop_id'],{})
            access=old.get('evidence',{}).get('access_problem','')
            if old.get('assessment_version')==VERSION and re.search(r'HTTP_(?:401|403|429)\b|robots_disallow',access):
                record=deepcopy(old)
                record.update(assessment_revision=REVISION,assessed_at=now(),
                    previous_assessment_path=old['assessment_path'],evidence_basis='prior_access_block_retained_no_retry')
            else:
                record = assessor(item, country=item['country'], prior=prior,
                                  existing=existing, existing_approved=approved)
        except Exception as exc:
            record = {'assessment_version':VERSION,'assessment_revision':REVISION,'shop_id':item['shop_id'],'name':item['name'],
                      'domain':item['domain'],'country':item['country'],'scraper_type':'MANUAL_REVIEW',
                      'reason':[type(exc).__name__], 'build_status':'NOT_BUILDABLE_WITH_CURRENT_EVIDENCE',
                      'database_write':False}
        body = record.pop('_listing_body',None)
        record.setdefault('website', f"https://{item['domain']}/" if item['domain'] and item['source_status'] in {'READY','DUPLICATE_DOMAIN'} else None)
        record['country_source'] = item.get('country_source')
        record['existing_scraper_status'] = qa.get('status', 'PRESENT_UNREVIEWED' if existing else 'NONE')
        record['example_urls'] = [e['url'] for e in record.get('examples',[])]
        if approved:
            record['existing_approval'] = {key:qa.get(key) for key in ('status','fingerprint','updated_at','run_id')}
        record.setdefault('assessed_at', now())
        record.setdefault('database_write', False)
        record.setdefault('migration_approved', False)
        record.setdefault('assessment_ready', False)
        record.update(assessment_id=assessment_id, queue_rows=item['queue_rows'], shop_id=item['shop_id'])
        if body and record.get('build_eligible') and scraper_type in {'AUTO',record['scraper_type']}:
            try:
                build_candidate(record, body, output/'candidates'/assessment_id)
            except Exception as exc:
                record.update(build_status='BUILD_REVIEW', build_attempts=1,
                              build_reason=type(exc).__name__, manual_test_required=True)
        elif record.get('build_eligible'):
            record['build_status'] = 'READY_OTHER_SELECTED_TYPE'
        record['assessment_path'] = f'assessments/v2/{slug(item["shop_id"])}/{assessment_id}.json'
        path = output/record['assessment_path']; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        index['shops'][item['shop_id']] = {k:record.get(k) for k in INDEX_FIELDS} | {
            'queue_rows':item['queue_rows'], 'assessment_path':record['assessment_path'], 'evidence':record.get('evidence',{})}
        results.append(record)
        (output/'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (output/'result.json').write_text(json.dumps({'schema_version':2,'database_write':False,
            'assessment_id':assessment_id,'processed':len(results),'results':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f"{item['domain']}: {record['scraper_type']} / {record.get('build_status')}",flush=True)
    return index, results


def overview(queue, metadata, index):
    result=[]
    for item in shops(queue,metadata):
        row={**item, **index.get('shops',{}).get(item['shop_id'],{})}
        row['review_status']='ASSESSED' if row.get('assessment_revision')==REVISION else 'NOT_YET_REVIEWED'
        result.append(row)
    return result


def csv_text(rows):
    stream=io.StringIO(); columns=list(INDEX_FIELDS)+['review_status','queue_rows','assessment_path',
        'active','vinyl','secondhand_only','new_used_distinguishable','public_prices','availability',
        'stable_urls','detail_checked','ean_valid','identity_details_proven','identity_listing_ratio',
        'sale_price_recognizable','cover_available','existing_ean_approved','access_problem']
    writer=csv.DictWriter(stream,fieldnames=columns); writer.writeheader()
    for row in rows:
        output={}
        for key in columns:
            value=row.get(key, row.get('evidence',{}).get(key))
            if isinstance(value,list):value='; '.join(map(str,value))
            if value is None:value=''
            value=str(value)
            if value.lstrip().startswith(('=','+','-','@','\t','\r')):value="'"+value
            output[key]=value
        writer.writerow(output)
    return stream.getvalue()


def section(rows):
    from collector.status import cell
    done=[r for r in rows if r.get('assessment_revision')==REVISION]
    counts=Counter(r['scraper_type'] for r in done)
    lines=['<!-- assessment-v2:start -->','## EAN / Artist + Title — aanvullende beoordeling', '',
           f'Beoordelingsrevisie: **{REVISION}**. Unieke shops/bronnen: **{len(rows)}**. Beoordeeld: **{len(done)}**. Open: **{len(rows)-len(done)}**.', '',
           ' | '.join(f'{key}: **{counts[key]}**' for key in ('EAN','ARTIST_TITLE','MANUAL_REVIEW','UNSUITABLE')), '',
           'Bestaande EAN-toelatingen blijven behouden. Nieuwe kandidaten wachten op handmatige tests; geen productieacceptatie.', '',
           '| Shop | Land | Type | Prioriteit | Bouwstatus | Reden | Kandidaat voor handmatige test |',
           '|---|---|---|---|---|---|---|']
    for row in rows:
        values=[]
        for key in ('name','country','scraper_type','priority','build_status','reason','candidate_ref'):
            value=row.get(key)
            if isinstance(value,list):value='; '.join(map(str,value))
            values.append(value or ('Nog te beoordelen' if key=='scraper_type' else '—'))
        lines.append('| '+' | '.join(cell(value) for value in values)+' |')
    return '\n'.join(lines+['<!-- assessment-v2:end -->',''])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('queue','progress','index','metadata','published','quality','output'):
        parser.add_argument('--'+option,type=Path,required=True)
    parser.add_argument('--batch-limit',type=int,default=100)
    parser.add_argument('--scraper-type',choices=('AUTO','EAN','ARTIST_TITLE'),default='AUTO')
    parser.add_argument('--run-id',required=True)
    args=parser.parse_args()
    run(load_queue(args.queue),json.loads(args.progress.read_text()),json.loads(args.index.read_text()),
        json.loads(args.metadata.read_text()),published=args.published,quality=json.loads(args.quality.read_text()),
        output=args.output,run_id=args.run_id,limit=args.batch_limit,scraper_type=args.scraper_type)


if __name__=='__main__':main()
