"""Encrypted snapshot checkpoint to GitHub with optimistic concurrency.

Requires a clean tracked checkout on main. No rebase/force push: an uncertain or
conflicting push stops the caller. Remote provider writes must be started only after
this function succeeds. Queue content is always encrypted before staging.
"""
import subprocess
from pathlib import Path
from secure_scan import write_encrypted

class CheckpointError(RuntimeError): pass

def cmd(repo,*args):
    p=subprocess.run(['git',*args],cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=45)
    if p.returncode: raise CheckpointError('git checkpoint operation failed: '+args[0])
    return p.stdout.strip()

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
    cmd(root,'push','origin','HEAD:main')
    # A successful push is the durable checkpoint. If push reports failure, do
    # not guess: the caller stops even if GitHub may have accepted it.
