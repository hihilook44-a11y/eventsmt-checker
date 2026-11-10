#!/usr/bin/env python3
"""Read-only provider reconciliation for one independently confirmed publication.

Never creates posts. A record is updated only when every candidate, destination,
source, media and idempotency key matches the provider's exact post.
"""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secure_scan import read_key, load_snapshot
from git_checkpoint import encrypted_git_checkpoint
from zernio_adapter import ZernioProvider, stable_idempotency_key
from candidate_pipeline import CandidatePipeline

POST_ID='6af3574d185f99d035290515'
SOURCE_ID='2119732969342746732'

def match_record(snapshot, provider, raw):
    post=raw.get('post') if isinstance(raw,dict) else None
    if not isinstance(post,dict) or post.get('_id')!=POST_ID:
        raise ValueError('post mismatch')
    content=post.get('content','')
    source='https://x.com/__eventsMT/status/'+SOURCE_ID
    if not isinstance(content,str) or source not in content.split():
        raise ValueError('source mismatch')
    matches=[(k,r) for k,r in snapshot.get('candidate_deliveries',{}).items()
             if k.split(':')[0]==SOURCE_ID and r.get('provider')=='zernio'
             and r.get('state')=='delivery_uncertain' and not r.get('post_id')]
    if len(matches)!=1: raise ValueError('uncertain record not unique')
    key,record=matches[0]
    if record.get('project')!=provider.profile or record.get('account')!=provider.account:
        raise ValueError('destination mismatch')
    if record.get('idempotency_key')!=stable_idempotency_key(record['account'],key,record.get('sha256','')):
        raise ValueError('saved idempotency mismatch')
    if post.get('metadata',{}).get('eventsmtPipelineKey')!=record['idempotency_key']:
        raise ValueError('provider idempotency metadata mismatch')
    media=post.get('mediaItems',[])
    if len(media)!=1 or media[0].get('url')!=record.get('media_id'):
        from urllib.parse import urlsplit
        saved=record.get('media_id')
        print('Media comparison:', {'items':len(media),'item_fields':sorted(media[0].keys()) if media and isinstance(media[0],dict) else [], 'saved_type':type(saved).__name__, 'saved_host':urlsplit(saved).hostname if isinstance(saved,str) else None, 'post_host':urlsplit(media[0].get('url','')).hostname if media and isinstance(media[0],dict) else None, 'same_path':bool(media and isinstance(saved,str) and isinstance(media[0],dict) and urlsplit(saved).path==urlsplit(media[0].get('url','')).path)}, flush=True)
        raise ValueError('media mismatch')
    platforms=[p for p in post.get('platforms',[]) if p.get('accountId')==provider.account and p.get('platform')=='youtube']
    if len(platforms)!=1 or platforms[0].get('status')!='published' or not platforms[0].get('platformPostId'):
        raise ValueError('youtube publication not established')
    return key,record

def main():
    f=read_key(); s=load_snapshot(f); p=ZernioProvider()
    raw=p._api('GET','/posts/'+POST_ID)
    key,record=match_record(s,p,raw)
    root=Path(__file__).resolve().parent.parent
    cp=lambda obj:encrypted_git_checkpoint(root,f,obj)
    record.update(state='delivery_recorded',post_id=POST_ID)
    cp(s)
    CandidatePipeline(s,cp,p).reconcile_published(key)
    print('Matched existing publication; source added to encrypted deduplication ledger.')
if __name__=='__main__': main()
