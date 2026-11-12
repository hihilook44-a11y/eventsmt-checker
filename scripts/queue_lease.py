#!/usr/bin/env python3
"""Fail-closed shared Git ref mutex for encrypted queue writers.

Never steal or expire leases; abandoned leases require operator reconciliation.
Owner identity is a unique Git commit, release uses git's compare-and-swap lease.
"""
import argparse, os, subprocess, time, uuid
from pathlib import Path
REF='refs/heads/wabi-encrypted-queue-lock'

def git(*args, check=True, env=None):
    p=subprocess.run(['git',*args],capture_output=True,text=True,timeout=45,env=env)
    if check and p.returncode: raise RuntimeError('git operation failed: '+args[0])
    return p

def acquire(token_path, wait_seconds=0):
    p=Path(token_path)
    if p.exists(): raise RuntimeError('lease token already exists; reconcile first')
    git('fetch','origin','main')
    head=git('rev-parse','FETCH_HEAD').stdout.strip()
    tree=git('rev-parse',head+'^{tree}').stdout.strip()
    env=os.environ.copy();env.update({'GIT_AUTHOR_NAME':'queue lease','GIT_AUTHOR_EMAIL':'queue-lease@localhost','GIT_COMMITTER_NAME':'queue lease','GIT_COMMITTER_EMAIL':'queue-lease@localhost'})
    marker=git('commit-tree',tree,'-p',head,'-m','Queue lease '+str(uuid.uuid4()),env=env).stdout.strip()
    end=time.monotonic()+wait_seconds
    while True:
        r=git('push','origin',f'{marker}:{REF}',check=False)
        # Push may be accepted even on transport error. Read back before deciding.
        observed=git('ls-remote','--refs','origin',REF,check=False)
        if observed.returncode: raise RuntimeError('lease outcome unknown; no queue writes')
        rows=observed.stdout.strip().splitlines()
        if rows and rows[0].split()[0]==marker:
            p.parent.mkdir(parents=True,exist_ok=True); p.write_text(marker+'\n'); os.chmod(p,0o600);return marker
        if r.returncode==0: raise RuntimeError('lease readback mismatch')
        if not rows: raise RuntimeError('lease create failed without active owner')
        if time.monotonic()>=end: raise RuntimeError('queue lease held; no queue writes')
        time.sleep(min(10,max(0,end-time.monotonic())))

def release(token_path):
    p=Path(token_path)
    if not p.exists():return
    marker=p.read_text().strip()
    if len(marker)!=40 or any(c not in '0123456789abcdef' for c in marker):raise RuntimeError('invalid lease token')
    result=git('push',f'--force-with-lease={REF}:{marker}','origin',f':{REF}',check=False)
    observed=git('ls-remote','--refs','origin',REF,check=False)
    if observed.returncode:raise RuntimeError('lease release unknown; retain token')
    rows=observed.stdout.strip().splitlines()
    if rows and rows[0].split()[0]==marker:raise RuntimeError('lease remains; retain token')
    if rows: raise RuntimeError('lease owner changed; retain token')
    p.unlink()
    if result.returncode: print('lease absent on readback after uncertain release')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('op',choices=['acquire','release']);ap.add_argument('--token',required=True);ap.add_argument('--wait',type=int,default=0);a=ap.parse_args()
    try:
        if a.op=='acquire':acquire(a.token,a.wait)
        else:release(a.token)
        print('queue lease '+('acquired' if a.op=='acquire' else 'released'))
    except Exception as e:
        print('queue lease stopped safely: '+str(e),file=__import__('sys').stderr);raise SystemExit(1)
