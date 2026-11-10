#!/usr/bin/env python3
"""Read-only provider reconciliation for one independently confirmed publication.

Never creates posts. A record is updated only when every candidate, destination,
source, media and idempotency key matches the provider's exact post.
"""
import hashlib, re, sys, urllib.request
from urllib.parse import urlsplit
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secure_scan import read_key, load_snapshot
from git_checkpoint import encrypted_git_checkpoint
from zernio_adapter import ZernioProvider, stable_idempotency_key
from candidate_pipeline import CandidatePipeline

POST_ID='6af3574d185f99d035290515'
SOURCE_ID='2119732969342746732'

def media_sha256(url):
    """Hash a bounded public Zernio media URL; never fetch arbitrary hosts."""
    if not isinstance(url,str): return None
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='media.zernio.com' or parsed.username or parsed.password:
        return None
    try:
        digest=hashlib.sha256(); total=0
        with urllib.request.urlopen(url,timeout=20) as response:
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>500_000_000: return None
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None

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
    if len(media)!=1 or not isinstance(media[0],dict):
        raise ValueError('media item mismatch')
    saved_url=record.get('media_id')
    post_url=media[0].get('url')
    expected=record.get('sha256')
    if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
        raise ValueError('review fingerprint missing')
    saved_hash=media_sha256(saved_url)
    post_hash=saved_hash if saved_url==post_url else media_sha256(post_url)
    if not saved_hash or not post_hash or saved_hash!=expected or post_hash!=expected:
        raise ValueError('media fingerprint mismatch')
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
