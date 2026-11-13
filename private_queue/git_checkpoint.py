"""Encrypted snapshot checkpoint to GitHub with optimistic concurrency.

Requires a clean tracked checkout on main. No rebase/force push: an uncertain or
conflicting push stops the caller. Remote provider writes must be started only after
this function succeeds. Queue content is always encrypted before staging.
"""
import subprocess, os, signal
from pathlib import Path
from secure_scan import write_encrypted

class CheckpointError(RuntimeError): pass

def cmd(repo,*args):
    # Kill the entire Git process group on timeout; git may have spawned a
    # remote helper which otherwise continues after the caller has stopped.
    proc=subprocess.Popen(['git',*args],cwd=repo,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        out,err=proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        proc.communicate()
        raise CheckpointError('git checkpoint operation timed out: '+args[0]) from None
    if proc.returncode: raise CheckpointError('git checkpoint operation failed: '+args[0])
    return out.strip()

def push_checkpoint(repo):
    # A timeout or transport error is not proof that a push failed. Never push
    # again here: accept it only if a fresh remote read shows this exact commit.
    expected=cmd(repo,'rev-parse','HEAD')
    try:
        cmd(repo,'push','origin','HEAD:main')
    except CheckpointError:
        try:
            rows=cmd(repo,'ls-remote','--refs','origin','refs/heads/main').splitlines()
            if len(rows)==1 and rows[0].split()==[expected,'refs/heads/main']:
                return
        except CheckpointError:
            pass
        raise CheckpointError('git push outcome uncertain; stop and reconcile') from None

def encrypted_git_checkpoint(repo,fernet,snapshot):
    root=Path(repo).resolve(); path=root/'private_queue'/'queue.enc'
    if cmd(root,'branch','--show-current')!='main': raise CheckpointError('main branch required')
    if cmd(root,'status','--porcelain','--untracked-files=no'): raise CheckpointError('tracked checkout is not clean')
    cmd(root,'fetch','origin','main')
    head=cmd(root,'rev-parse','HEAD'); remote=cmd(root,'rev-parse','FETCH_HEAD')
    if head!=remote: raise CheckpointError('remote changed; stop and reconcile')
    write_encrypted(fernet,snapshot,path)
    cmd(root,'add','--','private_queue/queue.enc')
    cmd(root,'commit','-m','Checkpoint encrypted candidate delivery')
    push_checkpoint(root)
