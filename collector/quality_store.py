"""Publish release evidence/health separately from credential-free collection."""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import subprocess
import time
from pathlib import Path

from collector.health import now

BRANCH = 'scraper-quality'
ROOT = 'quality'


def api(method, path, payload=None):
    command = ['gh','api','--method',method,f'repos/{os.environ["GITHUB_REPOSITORY"]}/{path}']
    if payload is not None: command += ['--input','-']
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True)
    if result.returncode: raise RuntimeError(result.stderr[:500])
    return json.loads(result.stdout)


def read(path, branch=BRANCH):
    try: data = api('GET',f'contents/{path}?ref={branch}')
    except RuntimeError as exc:
        if 'HTTP 404' in str(exc): return None, None
        raise
    return base64.b64decode(data['content']).decode(), data['sha']


def update(path, transform, *, branch=BRANCH):
    for attempt in range(10):
        text, sha = read(path, branch)
        content = transform(text)
        if content == text: return
        payload = {'message':f'Update scraper evidence: {path} [skip ci]', 'branch':branch,
                   'content':base64.b64encode(content.encode()).decode()}
        if sha: payload['sha'] = sha
        try: api('PUT',f'contents/{path}',payload);return
        except RuntimeError as exc:
            if 'HTTP 409' not in str(exc) or attempt == 9: raise
            time.sleep(random.uniform(.2, min(5, attempt+1)))


def health_update(previous, observation, *, mode, run_id, observed_at):
    record = dict(previous or {})
    # An older concurrent result must not overwrite a more recent observation.
    if record.get('last_run_id') == run_id or record.get('observed_at','') > observed_at: return record
    rows = int(observation.get('records',0))
    good = observation.get('status') == 'success' and rows > 0 and not observation.get('errors')
    if mode == 'price': good = good and observation.get('price_quality',{}).get('status') == 'pass'
    else: good = good and int(observation.get('detail_errors',0)) == 0 and int(observation.get('ean_records',0)) > 0
    consecutive = 0 if good else int(record.get('consecutive_failures',0))+1
    status = 'ACTIVE' if good else 'INCIDENT' if consecutive == 1 else 'REPAIR_REQUIRED'
    if record.get('status') == 'FROZEN': status = 'FROZEN'
    record.update(status=status, consecutive_failures=consecutive, last_run_id=run_id,
        observed_at=observed_at, records=rows, ean_records=observation.get('ean_records',0),
        reason=None if good else 'bounded_worker_quality_failed', updated_at=now())
    return record


def publish_health(result_path, run_id):
    result = json.loads(result_path.read_text())
    if result.get('database_write') is not False: raise ValueError('not a public result')
    mode = result['mode']
    if mode not in {'price','ean'}: raise ValueError('invalid mode')
    for observation in result['profiles']:
        name = Path(observation['profile']).stem
        if not __import__('re').fullmatch('[a-z0-9_]+',name): raise ValueError('unsafe profile slug')
        def transform(text):
            previous = json.loads(text) if text else {}
            return json.dumps(health_update(previous, observation, mode=mode,
                run_id=run_id, observed_at=result['started_at']),indent=2)+'\n'
        update(f'{ROOT}/health/{mode}/{name}.json',transform)
        current, _ = read(f'{ROOT}/health/{mode}/{name}.json')
        record = json.loads(current)
        if observation.get('domain'):
            update('scraper-status.md', lambda text: update_health_cell(
                text, observation['domain'], mode, record), branch='main')


def update_health_cell(text, domain, mode, record):
    """Keep the single central list current after each individual worker run."""
    if text is None: raise ValueError('central status document missing')
    marker = '<!-- quality-gate:start -->'
    if marker not in text: return text
    prefix, section = text.split(marker, 1)
    lines = section.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(f'| {domain} |'):
            cells = line.split('|')
            column = 7 if mode == 'price' else 8
            cells[column] = f" {record['status']} (run {record.get('last_run_id', 'unknown')}) "
            lines[index] = '|'.join(cells)
            break
    return prefix + marker + ''.join(lines)


def central_section(root):
    state = json.loads((root/'state.json').read_text())
    lines=['<!-- quality-gate:start -->','## Inhoudelijke toelatingscontrole', '',
        f"Laatste verwerking: {state.get('updated_at','nog niet gestart')}. Batch {state.get('batch',0)}.",
        'Maximaal 25 shops per batch; initiële proef en maximaal drie ondersteunde routeherstelpogingen.',
        'APPROVED = beperkte inhoudelijke bronproef geslaagd, geen productie- of volledige-catalogusgoedkeuring.',
        'Prijs en valuta zijn vergeleken met dezelfde productvariant; EANs zijn checksumgecontroleerd.', '',
        '| Shop | Batch | Toelating | Reparaties | Listing | Detail/EAN | Price health | EAN health | Reden/bewijs |',
        '|---|---:|---|---:|---:|---|---|---|---|']
    for slug,record in sorted(state['shops'].items()):
        e=record['evidence'];modes=[]
        for mode in ('price','ean'):
            p=root/'health'/mode/f'{slug}.json';h=json.loads(p.read_text()) if p.exists() else {}
            modes.append(h.get('status','NOT_RUN'))
        fields=[record['domain'],record['batch'],record['status'],record['repair_attempts'],
            e.get('listing_records',0),f"{e.get('valid_eans',0)}/{e.get('detail_checked',0)}",*modes,
            e.get('reason') or f"run {record['run_id']}"]
        lines.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in fields)+' |')
    lines+=['<!-- quality-gate:end -->']
    return '\n'.join(lines)+'\n'


def publish(root):
    # Fail on competing edits to the aggregate rather than overwriting them.
    snapshot_path=root/'state.json'
    original_path=root/'base-state.json'
    if snapshot_path.exists():
        snapshot=snapshot_path.read_text();original=original_path.read_text() if original_path.exists() else None
        def replace_state(text):
            if text != original and text != snapshot: raise ValueError('quality state changed concurrently; refusing overwrite')
            return snapshot
        update(f'{ROOT}/state.json',replace_state)
    for p in sorted(root.rglob('*')):
        if not p.is_file() or p.name in {'state.json','base-state.json'}:continue
        if '__pycache__' in p.parts or p.suffix not in {'.json','.py'}:continue
        if 'health' in p.relative_to(root).parts:
            value=json.loads(p.read_text())
            def merge_health(text):
                old=json.loads(text) if text else {}
                # Keep observations published after the successful QA.
                return json.dumps(old if old.get('observed_at','') > value.get('last_quality_check_at', value.get('last_known_good','')) else value,indent=2)+'\n'
            update(f'{ROOT}/{p.relative_to(root).as_posix()}',merge_health)
        else:
            update(f'{ROOT}/{p.relative_to(root).as_posix()}',lambda _,p=p:p.read_text())
    if not snapshot_path.exists():return
    section=central_section(root)
    def render(text):
        if text is None:raise ValueError('central status document missing')
        marker='<!-- quality-gate:start -->'
        prefix=text.split(marker,1)[0].rstrip()
        suffix=''
        if marker in text:
            tail=text.split(marker,1)[1]
            if '<!-- quality-gate:end -->' in tail:suffix=tail.split('<!-- quality-gate:end -->',1)[1].strip()
        return prefix+'\n\n'+section+suffix
    update('scraper-status.md',render,branch='main')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--result',type=Path)
    parser.add_argument('--run-id',default='unknown')
    args=parser.parse_args()
    if args.result:publish_health(args.result,args.run_id)
    elif args.root:publish(args.root)
    else:parser.error('--root or --result required')


if __name__=='__main__':main()
