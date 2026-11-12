#!/usr/bin/env python3
"""Local read-only discovery with shared queue lease and optimistic Git push."""
import fcntl,json,os,subprocess,sys,tempfile
from pathlib import Path
import queue_lease
REPO='hihilook44-a11y/eventsmt-checker'
KEY=Path('/home/user/workspace/eventsMT/.private_secrets/queue_fernet.key')

def run(args,cwd=None,env=None):
    return subprocess.run(args,cwd=cwd,env=env,text=True,capture_output=True,timeout=330)

def main():
    state=Path.home()/'.local/state/eventsmt';state.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(state/'local-source.lock','a') as lock:
        os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        token=state/'remote-queue-lease'
        if token.exists(): raise RuntimeError('earlier lease needs reconciliation')
        repo=Path(__file__).resolve().parent.parent
        os.chdir(repo)
        history=run(['gh','run','list','-R',REPO,'--limit','50','--json','workflowName,status'])
        if history.returncode:raise RuntimeError('run history unavailable')
        names={'Encrypted private candidate queue','Conditional reviewed compilation delivery','Prepare private media for review','Reconcile one verified Zernio post','Reconcile reviewed delivery','One-shot WoopSocial upload and draft verification'}
        if any(x.get('workflowName') in names and x.get('status') not in ('completed',) for x in json.loads(history.stdout)):
            print(json.dumps({'fallback':'active_run_skip'}));return
        queue_lease.acquire(token)
        try:
            # A run may have started between history and the shared lease.
            history=run(['gh','run','list','-R',REPO,'--limit','50','--json','workflowName,status'])
            if history.returncode:raise RuntimeError('run history unavailable after lease')
            if any(x.get('workflowName') in names and x.get('status')!='completed' for x in json.loads(history.stdout)):
                print(json.dumps({'fallback':'active_run_skip'}));return
            with tempfile.TemporaryDirectory(prefix='eventsmt-fallback-') as td:
                clone=Path(td)/'repo'
                x=run(['git','clone','--quiet','--no-hardlinks',str(repo),str(clone)])
                if x.returncode:raise RuntimeError('isolated clone failed')
                x=run(['git','remote','get-url','origin'],cwd=repo)
                if x.returncode:raise RuntimeError('remote unavailable')
                remote=x.stdout.strip()
                if run(['git','remote','set-url','origin',remote],cwd=clone).returncode:raise RuntimeError('remote setup failed')
                if run(['git','fetch','origin','main'],cwd=clone).returncode:raise RuntimeError('remote fetch failed')
                if run(['git','reset','--hard','FETCH_HEAD'],cwd=clone).returncode:raise RuntimeError('checkout refresh failed')
                env=os.environ.copy();env['PRIVATE_QUEUE_FERNET_KEY']=KEY.read_text().strip()
                result=run(['uv','run','--no-project','--with','cryptography==45.0.7','python','private_queue/secure_scan.py'],cwd=clone,env=env)
                if result.returncode:print(json.dumps({'fallback':'scan_failed','state_preserved':True}));return
                try: summary=json.loads(result.stdout.strip().splitlines()[-1])
                except Exception:raise RuntimeError('invalid scan response')
                if run(['git','config','user.name','eventsmt automation'],cwd=clone).returncode or run(['git','config','user.email','eventsmt@localhost'],cwd=clone).returncode:raise RuntimeError('git identity failed')
                if run(['git','add','private_queue/queue.enc'],cwd=clone).returncode:raise RuntimeError('queue stage failed')
                if run(['git','commit','-m','Checkpoint safe local source scan'],cwd=clone).returncode:raise RuntimeError('queue commit failed')
                push=run(['git','push','origin','HEAD:main'],cwd=clone)
                # No retries. A failed push may have succeeded or remote may have moved.
                if push.returncode:raise RuntimeError('queue push uncertain or remote changed; reconcile')
                print(json.dumps({'fallback':'committed','summary':summary}))
        finally:
            queue_lease.release(token)
if __name__=='__main__':
    try:main()
    except Exception as e: print('fallback stopped safely: '+str(e),file=sys.stderr);raise SystemExit(1)
