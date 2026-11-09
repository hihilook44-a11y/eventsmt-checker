#!/usr/bin/env python3
"""Fail-closed private discovery for Wabi's two-hour checks; never posts video.

A 404 from FxTwitter may be an empty response or an upstream error. It is not
considered a trustworthy end marker. Restart a fresh scan at another page size;
never combine partial scans or advance queue/checkpoint without bounded overlap.
The persistent Computer is not an independent scheduler.
"""
import argparse, copy, fcntl, json, os, time, re
from pathlib import Path
from paginated_candidates import run
from incremental_queue import transition, atomic_write
ROOT=Path(__file__).resolve().parent

def apply_scan(scan, ledger, old, started_at):
    if not isinstance(old,dict) or not isinstance(old.get('baseline_epoch'),(float,int)):
        raise ValueError('Existing private baseline required')
    if scan.get('errors') or not scan.get('pages'):
        raise ValueError('Source scan failed')
    # Initialization deliberately scans as far back as the old queue baseline;
    # subsequent checks must reach the start of the previous successful scan.
    cutoff=old.get('last_successful_scan_epoch',old['baseline_epoch'])
    if not isinstance(cutoff,(float,int)) or cutoff > started_at:
        raise ValueError('Invalid discovery checkpoint')
    all_timestamps=[t for page in scan['pages'] for t in page.get('timestamps',[])]
    if not scan.get('end_of_timeline_seen') and (not all_timestamps or min(all_timestamps)>cutoff):
        raise ValueError('Insufficient page coverage to reach prior checkpoint')
    state,counts=transition(scan,ledger,old)
    state['last_successful_scan_epoch']=started_at
    return state,counts

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--max-pages',type=int,default=5);ap.add_argument('--state',default=str(ROOT/'incremental_private_state_20261108.json')); ap.add_argument('--ledger',default=str(ROOT/'published_sources.json'));a=ap.parse_args()
    if not 1<=a.max_pages<=20: ap.error('max-pages must be 1–20')
    statepath=Path(a.state).resolve();ledgerpath=Path(a.ledger).resolve()
    if statepath==ledgerpath:raise ValueError('state cannot overwrite ledger')
    with open(str(statepath)+'.lock','a') as lock:
        os.chmod(str(statepath)+'.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        old=json.loads(statepath.read_text(encoding='utf-8'));ledger=json.loads(ledgerpath.read_text(encoding='utf-8'))
        started_at=int(time.time()); reasons=[]
        for count in (100,50):
            scan=run(a.max_pages,count)
            try:
                updated,stats=apply_scan(scan,ledger,old,started_at)
            except ValueError as e:
                reasons.append(f'count={count}: {e}')
                for error in scan.get('errors',[]):
                    m=re.match(r'Page (\d+): HTTPError: HTTP Error (\d{3}):',str(error))
                    if m: reasons.append('page='+m.group(1)+' http='+m.group(2))
                continue
            atomic_write(statepath,updated)
            print(json.dumps({**stats,'pages_checked':len(scan['pages']),'page_size':count,
                              'more_pages_available':scan['next_cursor_available'],
                              'publication_performed':False,'audio_verified':False}))
            return 0
        print(json.dumps({'success':False,'reasons':reasons,'queue_unchanged':True}))
        return 2
if __name__=='__main__':raise SystemExit(main())
