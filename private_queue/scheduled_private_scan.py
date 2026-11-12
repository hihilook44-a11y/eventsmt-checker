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
    if not isinstance(old,dict) or not isinstance(old.get('baseline_epoch'),(float,int)) or isinstance(old.get('baseline_epoch'),bool):
        raise ValueError('Existing private baseline required')
    if not isinstance(scan,dict) or not isinstance(scan.get('pages'),list) or not scan['pages']:
        raise ValueError('Source scan failed')
    # Initialization deliberately scans as far back as the old queue baseline;
    # subsequent checks must reach the start of the previous successful scan.
    cutoff=old.get('last_successful_scan_epoch',old['baseline_epoch'])
    if not isinstance(cutoff,(float,int)) or isinstance(cutoff,bool) or not isinstance(started_at,(float,int)) or started_at < cutoff:
        raise ValueError('Invalid discovery checkpoint')
    page_numbers=[]; all_timestamps=[]
    for page in scan['pages']:
        if not isinstance(page,dict) or not isinstance(page.get('timestamps'),list):
            raise ValueError('Invalid page evidence')
        page_number=page.get('page')
        if not isinstance(page_number,int) or isinstance(page_number,bool):
            raise ValueError('Invalid page sequence')
        page_numbers.append(page_number)
        all_timestamps.extend(t for t in page['timestamps']
                              if isinstance(t,(int,float)) and not isinstance(t,bool))
    if page_numbers != list(range(1,len(page_numbers)+1)):
        raise ValueError('Non-contiguous page sequence')
    if not all_timestamps or min(all_timestamps)>cutoff:
        raise ValueError('Insufficient page coverage to reach prior checkpoint')

    errors=scan.get('errors') or []
    partial=bool(errors)
    if partial:
        # Only a single page-fetch failure immediately after contiguous pages is
        # recoverable, and only after their timestamps overlap the old checkpoint.
        # Cursor loops, malformed results and other errors remain fail-closed.
        if len(errors)!=1 or not scan.get('next_cursor_available'):
            raise ValueError('Non-recoverable source scan error')
        match=re.fullmatch(r'Page (\d+): (?:HTTPError|URLError|TimeoutError|ConnectionError|RemoteDisconnected|OSError): .*',str(errors[0]))
        if not match or int(match.group(1))!=page_numbers[-1]+1:
            raise ValueError('Non-recoverable source scan error')

    # The queue transition rejects all errors by design. After the checks above,
    # this is a deliberately bounded partial batch, not a claim of full coverage.
    accepted_scan=copy.deepcopy(scan)
    accepted_scan['errors']=[]
    state,counts=transition(accepted_scan,ledger,old)
    if partial:
        # Do not advance beyond the checkpoint actually reached. Re-scanning this
        # overlap next time is safe; deduplication prevents duplicate queue items.
        state['last_successful_scan_epoch']=cutoff
        state['last_partial_scan_epoch']=started_at
    else:
        state['last_successful_scan_epoch']=started_at
        state.pop('last_partial_scan_epoch',None)
    counts['partial_scan']=partial
    counts['checkpoint_advanced']=not partial
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
        # The public /media route has recently returned intermittent 404/500s,
        # while /statuses is currently serving video posts reliably. Prefer the
        # broader timeline and retain strict overlap checks before advancing state.
        partial_result=None
        for endpoint,count,pages in (("statuses",100,min(20,a.max_pages * 4)),("media",100,a.max_pages),("media",50,a.max_pages)):
            scan=run(pages,count,endpoint)
            try:
                updated,stats=apply_scan(scan,ledger,old,started_at)
            except ValueError as e:
                reasons.append(f'endpoint={endpoint} count={count}: {e}')
                for error in scan.get('errors',[]):
                    m=re.match(r'Page (\d+): HTTPError: HTTP Error (\d{3}):',str(error))
                    if m: reasons.append('page='+m.group(1)+' http='+m.group(2))
                continue
            if stats['partial_scan']:
                # Preserve the validated overlapping batch, but try the other
                # routes for a clean scan before settling on a frozen checkpoint.
                if partial_result is None:
                    partial_result=(updated,stats,scan,endpoint,count)
                continue
            if partial_result is not None:
                # Keep candidates already found in the earlier validated partial
                # batch; the later scan still must independently reach the old
                # checkpoint and can never authorize unchecked publication.
                prior_state,prior_stats,_,_,_=partial_result
                updated,stats=apply_scan(scan,ledger,prior_state,started_at)
                stats['new_candidates']+=prior_stats['new_candidates']
            atomic_write(statepath,updated)
            print(json.dumps({**stats,'pages_checked':len(scan['pages']),'page_size':count,
                              'more_pages_available':scan['next_cursor_available'],'endpoint':endpoint,
                              'publication_performed':False,'audio_verified':False}))
            return 0
        if partial_result is not None:
            updated,stats,scan,endpoint,count=partial_result
            atomic_write(statepath,updated)
            print(json.dumps({**stats,'pages_checked':len(scan['pages']),'page_size':count,
                              'more_pages_available':scan['next_cursor_available'],'endpoint':endpoint,
                              'publication_performed':False,'audio_verified':False}))
            return 0
        print(json.dumps({'success':False,'reasons':reasons,'queue_unchanged':True}))
        return 2
if __name__=='__main__':raise SystemExit(main())
