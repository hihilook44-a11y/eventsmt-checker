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
WORKFLOWS={'private-queue.yml':3600,'compilation-delivery.yml':86400}
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
        # A later run may be an independent manual or scheduled run, not this
        # uncertain request. Never infer its acceptance from timestamp alone.
        if receipt['state'] in {'attempting','unknown'}:
            return 'awaiting_dispatch_readback' if (now-attempted).total_seconds()<interval else 'unresolved_dispatch'
        if receipt.get('request_version') == 2:
            run_id=receipt.get('run_id')
            if not isinstance(run_id,int) or isinstance(run_id,bool) or run_id <= 0:
                return 'unresolved_dispatch'
            if not any(r.get('databaseId') == run_id for r in runs):
                return 'awaiting_dispatch_readback' if (now-attempted).total_seconds()<interval else 'unresolved_dispatch'
        elif any(t>=attempted-timedelta(seconds=3) for t in times):pass
        elif (now-attempted).total_seconds()<interval:return 'awaiting_dispatch_readback'
        else:return 'unresolved_dispatch'
    if times and (now-max(times)).total_seconds()<interval:return 'recent_run'
    return 'due'

def queue_parent_covers(runs,jobs_by_id,now,interval):
    """A recent hourly parent check already runs the reusable queue workflow."""
    for run in runs:
        if run.get('status') in ACTIVE:
            return True
        if (now-when(run['createdAt'])).total_seconds() >= interval:
            continue
        jobs=jobs_by_id.get(str(run.get('databaseId')),[])
        for job in jobs:
            if job.get('name','').startswith('backup-private-queue /') and (
                job.get('status') in ACTIVE or
                (job.get('status') == 'completed' and job.get('conclusion') == 'success')
            ):
                return True
    return False

def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        os.chmod(f.name,0o600);json.dump(data,f);name=f.name
    os.replace(name,path)

def call(args):
    return subprocess.run(['gh',*args],capture_output=True,text=True,timeout=40)

def parse_dispatch(receipt):
    # A 200 response with its run ID binds the exact API request to a run.
    # Errors, missing/invalid JSON, and unexpected success bodies stay unknown;
    # they must never be retried blindly or matched by a nearby timestamp.
    if receipt.returncode != 0:return None
    try:
        run_id=json.loads(receipt.stdout)['workflow_run_id']
        return run_id if isinstance(run_id,int) and not isinstance(run_id,bool) and run_id>0 else None
    except (ValueError,TypeError,KeyError):return None

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
            runs=json.loads(r.stdout)
            prior=state.get(workflow) or {}
            run_id=prior.get('run_id')
            if prior.get('state')=='accepted' and prior.get('request_version')==2 and isinstance(run_id,int) and not isinstance(run_id,bool) and run_id>0 and not any(x.get('databaseId')==run_id for x in runs):
                exact=call(['run','view',str(run_id),'-R',REPO,'--json','databaseId,event,status,conclusion,createdAt,url'])
                if exact.returncode==0:
                    data=json.loads(exact.stdout)
                    if data.get('databaseId')==run_id:runs.append(data)
            decision=decide(runs,prior,now,interval)
            if workflow=='private-queue.yml' and decision=='due':
                parents_result=call(['run','list','-R',REPO,'--workflow','Source availability check','--limit','30','--json','databaseId,status,conclusion,createdAt,url'])
                if parents_result.returncode:raise RuntimeError('source-check history unavailable; no queue dispatch')
                parents=json.loads(parents_result.stdout);jobs_by_id={}
                for parent in parents:
                    age=(now-when(parent['createdAt'])).total_seconds()
                    if parent.get('status') in ACTIVE or age >= interval:
                        continue
                    detail=call(['run','view',str(parent['databaseId']),'-R',REPO,'--json','jobs'])
                    if detail.returncode:raise RuntimeError('source-check job state unavailable; no queue dispatch')
                    jobs_by_id[str(parent['databaseId'])]=json.loads(detail.stdout).get('jobs',[])
                if queue_parent_covers(parents,jobs_by_id,now,interval):decision='recent_source_check'
            item={'workflow':workflow,'decision':decision,'latest':runs[0] if runs else None}
            if decision=='due' and a.apply:
                state[workflow]={'state':'attempting','attempted_at':now.isoformat(),'request_version':2};atomic(a.state,state)
                try:
                    sent=call(['api','--method','POST',f'repos/{REPO}/actions/workflows/{workflow}/dispatches','-f','ref=main','-F','return_run_details=true'])
                    run_id=parse_dispatch(sent)
                    state[workflow]['state']='accepted' if run_id is not None else 'unknown'
                    if run_id is not None:state[workflow]['run_id']=run_id
                except Exception:
                    state[workflow]['state']='unknown';atomic(a.state,state);raise
                atomic(a.state,state);item['dispatch']=state[workflow]['state']
            out.append(item)
        print(json.dumps({'checked_at':now.isoformat(),'applied':a.apply,'fallback':fallback,'workflows':out}))
if __name__=='__main__':main()
