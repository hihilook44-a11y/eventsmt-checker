#!/usr/bin/env python3
"""Reconcile known posts and safely recover a recent idempotent Zernio timeout."""
import json
import os
from pathlib import Path
from secure_scan import read_key,load_snapshot
from workflow_pipeline import (reconcile_known_deliveries,recover_uncertain_scheduled,
                               reconciliation_summary,zernio_scheduling_enabled)
from git_checkpoint import encrypted_git_checkpoint
from woopsocial_adapter import Provider
from zernio_adapter import ZernioProvider
from audio_review import verifier_with_silent_sources as review_verifier

def main():
    f=read_key();s=load_snapshot(f)
    cp=lambda obj:encrypted_git_checkpoint(Path(__file__).resolve().parent.parent,f,obj)
    providers={}
    if zernio_scheduling_enabled():
        providers['zernio']=ZernioProvider()
    if os.environ.get('WOOPSOCIAL_API_KEY','').strip():
        providers['woopsocial']=Provider()
    if not providers:
        raise ValueError('no configured provider for reconciliation')
    provider=next(iter(providers.values()))
    zernio=providers.get('zernio')
    if zernio:
        verifier=review_verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
        if recover_uncertain_scheduled(s,cp,zernio,verifier):
            print('Recovered one uncertain Zernio post with its original idempotency key.')
    reconcile_known_deliveries(s,cp,provider,providers)
    print('Persisted delivery summary:',json.dumps(reconciliation_summary(s),sort_keys=True))
    for r in s.get('candidate_deliveries',{}).values():
        if r.get('state')=='published' and r.get('external_post_url','').startswith(('https://www.youtube.com/','https://youtube.com/','https://youtu.be/')):
            print('Published YouTube URL:',r['external_post_url'])
if __name__=='__main__': main()
