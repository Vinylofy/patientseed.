"""Publish additive assessments using the existing progress/build branches."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil

from collector import quality_store
from collector.assessment_batch import csv_text, overview, section
from collector.build_scrapers import slug
from collector.manual_run import load_queue
from collector.publish_generated import publish as publish_builds

BRANCH='collector-progress'
INDEX='assessments/v2/index.json'


def prepare(directory):
    directory.mkdir(parents=True,exist_ok=True)
    raw,_=quality_store.read(INDEX,branch=BRANCH)
    state=json.loads(raw) if raw else {'schema_version':2,'shops':{}}
    (directory/'index.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Loaded version-2 assessments:',len(state['shops']))


def immutable(path, content):
    def transform(previous):
        if previous is not None and previous != content:
            raise ValueError('historical assessment cannot be overwritten')
        return content
    quality_store.update(path,transform,branch=BRANCH)


def publish(directory, queue_path, metadata_path):
    result_path=directory/'result.json'
    if not result_path.exists():
        print('No completed shop assessments to publish');return
    result=json.loads(result_path.read_text())
    if result.get('schema_version')!=2 or result.get('database_write') is not False:
        raise ValueError('not a read-only assessment batch')
    records=result['results'];assessment_id=result['assessment_id']
    if not re.fullmatch('v2-[A-Za-z0-9_-]{1,80}',assessment_id):raise ValueError('unsafe assessment ID')
    valid_ids={s['shop_id'] for s in overview(load_queue(queue_path),json.loads(metadata_path.read_text()),{'shops':{}})}
    for record in records:
        expected=f'assessments/v2/{slug(record["shop_id"])}/{assessment_id}.json'
        if record['shop_id'] not in valid_ids or record['assessment_path']!=expected:
            raise ValueError('assessment outside supplied queue')
        immutable(expected,(directory/expected).read_text())
    # Only self-tested files enter candidates; incomplete failed build files stay
    # in the artifact and cannot appear as a working candidate.
    safe=directory/'publish-candidates';safe.mkdir(exist_ok=True)
    for record in records:
        if record.get('build_status')!='BUILT_AWAITING_MANUAL_TEST':continue
        name=slug(record['domain'])
        for suffix in ('.json','.py'):
            shutil.copyfile(directory/'candidates'/assessment_id/(name+suffix),safe/(name+suffix))
    publish_builds(safe,prefix='collector/candidates/v2/'+assessment_id,immutable=True)
    local=json.loads((directory/'index.json').read_text())
    def merge(raw):
        state=json.loads(raw) if raw else {'schema_version':2,'shops':{}}
        for record in records:
            key=record['shop_id'];previous=state['shops'].get(key,{})
            if previous.get('assessed_at','') > (record.get('assessed_at') or ''):continue
            state['shops'][key]=local['shops'][key]
        return json.dumps(state,ensure_ascii=False,indent=2)+'\n'
    quality_store.update(INDEX,merge,branch=BRANCH)
    raw,_=quality_store.read(INDEX,branch=BRANCH)
    current=json.loads(raw)
    rows=overview(load_queue(queue_path),json.loads(metadata_path.read_text()),current)
    groups={'all':rows,
            'artist-title':[r for r in rows if r.get('scraper_type')=='ARTIST_TITLE'],
            'ean':[r for r in rows if r.get('scraper_type')=='EAN'],
            'manual-review':[r for r in rows if r.get('scraper_type')=='MANUAL_REVIEW'],
            'unsuitable':[r for r in rows if r.get('scraper_type')=='UNSUITABLE'],
            'assessment-ready':[r for r in rows if r.get('assessment_ready')]}
    for name,selected in groups.items():
        content=csv_text(selected)
        quality_store.update('assessment-exports/v2/'+name+'.csv',lambda _,content=content:content,branch=BRANCH)
    block=section(rows)
    def render(text):
        if text is None:raise ValueError('central status document missing')
        start,end='<!-- assessment-v2:start -->','<!-- assessment-v2:end -->'
        if start in text:
            before,tail=text.split(start,1)
            if end not in tail:raise ValueError('incomplete central assessment section')
            text=before+tail.split(end,1)[1]
        return text.rstrip()+'\n\n'+block
    quality_store.update('scraper-status.md',render,branch='main')
    print('Published',len(records),'versioned assessments; all exports and central status updated')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('prepare','publish'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--queue',type=Path)
    parser.add_argument('--metadata',type=Path)
    args=parser.parse_args()
    if args.operation=='prepare':prepare(args.root)
    else:publish(args.root,args.queue,args.metadata)


if __name__=='__main__':main()
