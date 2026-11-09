#!/usr/bin/env python3
"""Private incremental queue for eventsMT. Never uploads or marks a source published.

Input is a completed paginated scan: errors refuse the whole update. The first scan is a
baseline, not a backlog; later scans queue unseen posts at or after its latest observed
UTC timestamp. This cannot guarantee complete source coverage or ordered timelines.
All queued material is unreviewed and must not be published until separately reviewed.
"""
import argparse, copy, fcntl, json, os, tempfile
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def stamp(value):
    try:
        if not isinstance(value, str): raise ValueError('date missing')
        try: dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError: dt = parsedate_to_datetime(value)
        if dt.tzinfo is None: raise ValueError('date lacks timezone')
        return dt.astimezone(timezone.utc).timestamp()
    except Exception as exc:
        raise ValueError('invalid post date') from exc

def key(item):
    pid = str(item.get('post_id', '')); mid = str(item.get('media_id') or '')
    if not pid.isdigit() or not mid.isdigit():
        raise ValueError('candidate lacks stable post/media id')
    return pid + ':' + mid

def transition(scan, ledger, old):
    if not isinstance(scan, dict) or not isinstance(scan.get('candidates'), list) or scan.get('errors'):
        raise ValueError('invalid or failed scan')
    if not isinstance(ledger, dict) or not isinstance(ledger.get('published_source_ids'), list):
        raise ValueError('invalid publication ledger')
    blocked = set(map(str, ledger['published_source_ids']))
    clean = {}
    for item in scan['candidates']:
        if not isinstance(item, dict): raise ValueError('invalid candidate')
        k = key(item); stamp(item.get('created_at'))
        if item.get('music_checked') is not False or item.get('published') is not False:
            raise ValueError('scan candidate has unexpected state')
        clean[k] = item
    if old is None:
        if not clean: raise ValueError('cannot establish baseline from empty scan')
        baseline = max(stamp(x['created_at']) for x in clean.values())
        state = {'version': 1, 'baseline_epoch': baseline,
                 'seen_keys': sorted(clean), 'pending': [], 'runs': 1}
        return state, {'baseline_initialized': True, 'new_candidates': 0, 'pending_total': 0}
    if not isinstance(old, dict) or old.get('version') != 1 or not isinstance(old.get('baseline_epoch'), (int,float)) or not isinstance(old.get('seen_keys'), list) or not isinstance(old.get('pending'), list):
        raise ValueError('invalid discovery state')
    state = copy.deepcopy(old); seen = set(state['seen_keys']); pending = []
    pending_keys = set()
    for item in state['pending']:
        k = key(item)
        if str(item['post_id']) not in blocked and k not in pending_keys:
            pending.append(item); pending_keys.add(k)
    new = 0
    for k,item in clean.items():
        if k not in seen and k not in pending_keys and str(item['post_id']) not in blocked and stamp(item['created_at']) >= state['baseline_epoch']:
            q = {**item, 'music_checked': False, 'published': False,
                 'decision': 'awaiting_audio_review', 'publish_allowed': False}
            pending.append(q); pending_keys.add(k); new += 1
        seen.add(k)
    state['seen_keys'] = sorted(seen); state['pending'] = pending
    state['runs'] = int(state.get('runs', 0)) + 1
    return state, {'baseline_initialized':False, 'new_candidates':new, 'pending_total':len(pending)}

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.incremental-', dir=str(path.parent), text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(data,out,ensure_ascii=False,indent=2); out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def main():
    p=argparse.ArgumentParser();p.add_argument('scan');p.add_argument('--ledger',required=True);p.add_argument('--state',required=True);a=p.parse_args()
    scanpath=Path(a.scan).resolve(); ledgerpath=Path(a.ledger).resolve(); statepath=Path(a.state).resolve()
    if statepath in (scanpath, ledgerpath): raise ValueError('state cannot overwrite inputs')
    statepath.parent.mkdir(parents=True,exist_ok=True)
    with open(str(statepath)+'.lock','a') as lock:
        os.chmod(str(statepath)+'.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        scan=json.loads(scanpath.read_text()); ledger=json.loads(ledgerpath.read_text())
        old=json.loads(statepath.read_text()) if statepath.exists() else None
        state, result=transition(scan, ledger, old)
        atomic_write(statepath,state)
    print(json.dumps({**result,'timeline_complete':bool(scan.get('end_of_timeline_seen')),'publish_performed':False,'audio_verified':False}))
if __name__=='__main__': main()
