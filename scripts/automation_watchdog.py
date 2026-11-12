#!/usr/bin/env python3
"""Wabi two-hour watchdog for delayed GitHub cron; no media/secret access.

Read-only by default. --apply dispatches existing authorized workflows only when
no recent/active run exists. Unknown dispatch outcomes are durably retained to
prevent blind resubmission. The workflows retain audio/recency/dedup safeguards.
Run from the user's already authenticated Computer, not an independent daemon.
"""
import argparse,fcntl,json,os,subprocess,tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
REPO='hihilook44-a11y/eventsmt-checker'
WORKFLOWS={'private-queue.yml':7200,'compilation-delivery.yml':86400}
ACTIVE={'queued','in_progress','waiting','requested','pending'}

def when(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('missing timezone')
    return parsed.astimezone(timezone.utc)

def decide(runs,receipt,now,interval):
    if not isinstance(runs,list) or any(not isinstance(r,dict) for r in runs):raise ValueError('invalid runs')
    if any(r.get('status') in ACTIVE for r in runs):return 'active_run'
    times=[when(r['createdAt']) for r in runs]
    if receipt and receipt.get('state') in {'attempting','accepted','unknown'}:
        attempted=when(receipt['attempted_at'])
        if any(t>=attempted-timedelta(seconds=3) for t in times):pass
        elif (now-attempted).total_seconds()<interval:return 'awaiting_dispatch_readback'
        else:return 'unresolved_dispatch'
    if times and (now-max(times)).total_seconds()<interval:return 'recent_run'
    return 'due'

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        os.chmod(f.name,0o600);json.dump(data,f);name=f.name
    os.replace(name,path)

def call(args):
    return subprocess.run(['gh',*args],capture_output=True,text=True,timeout=40)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');ap.add_argument('--state',type=Path,default=Path.home()/'.local/state/eventsmt/watchdog.json');a=ap.parse_args()
    a.state.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(str(a.state)+'.lock','a') as lock:
        os.chmod(str(a.state)+'.lock',0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        state=json.loads(a.state.read_text()) if a.state.exists() else {}
        fallback={'state':'not_requested'}
        if a.apply:
            try:
                local=subprocess.run(['python3','scripts/local_source_fallback.py'],capture_output=True,text=True,timeout=360)
                if local.returncode: fallback={'state':'failed_safely'}
                else:
                    try: fallback=json.loads(local.stdout.strip().splitlines()[-1])
                    except (IndexError,ValueError):fallback={'state':'invalid_result'}
            except (subprocess.TimeoutExpired,OSError):fallback={'state':'outcome_unknown'}
        now=datetime.now(timezone.utc);out=[]
        for workflow,interval in WORKFLOWS.items():
            r=call(['run','list','-R',REPO,'--workflow',workflow,'--limit','30','--json','databaseId,event,status,conclusion,createdAt,url'])
            if r.returncode:raise RuntimeError('run history unavailable; no dispatch')
            runs=json.loads(r.stdout);decision=decide(runs,state.get(workflow),now,interval)
            item={'workflow':workflow,'decision':decision,'latest':runs[0] if runs else None}
            if decision=='due' and a.apply:
                state[workflow]={'state':'attempting','attempted_at':now.isoformat()};atomic(a.state,state)
                try:
                    sent=call(['workflow','run',workflow,'-R',REPO,'--ref','main'])
                    state[workflow]['state']='accepted' if sent.returncode==0 else 'unknown'
                except Exception:
                    state[workflow]['state']='unknown';atomic(a.state,state);raise
                atomic(a.state,state);item['dispatch']=state[workflow]['state']
            out.append(item)
        print(json.dumps({'checked_at':now.isoformat(),'applied':a.apply,'fallback':fallback,'workflows':out}))
if __name__=='__main__':main()
