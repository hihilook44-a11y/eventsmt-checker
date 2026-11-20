#!/usr/bin/env python3
"""Reconcile one provider-confirmed publication; no uploads or posts are created."""
import json, urllib.parse, urllib.request, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secure_scan import read_key, load_snapshot
from git_checkpoint import encrypted_git_checkpoint
from zernio_adapter import ZernioProvider
SOURCE='2123499574560178192'
POST='6aff530d9923ba416202b53f'
VIDEO='CioXam2fmuU'
CHANNEL='Mt Fivem- زيكو'

def reconcile(snapshot,provider,raw,normalized,verified):
    if not verified or not provider.verify_destination(provider.profile,provider.account):
        raise ValueError('destination or public video not verified')
    post=raw.get('post',{})
    if post.get('_id')!=POST or 'https://x.com/__eventsMT/status/'+SOURCE not in str(post.get('content','')).split():
        raise ValueError('post or source mismatch')
    pairs=[(k,r) for k,r in snapshot.get('candidate_deliveries',{}).items() if k.split(':')[0]==SOURCE and r.get('post_id')==POST]
    if len(pairs)!=1: raise ValueError('record not unique')
    key,record=pairs[0]
    if record.get('provider')!='zernio' or record.get('state') not in {'delivery_failed','published'} or record.get('project')!=provider.profile or record.get('account')!=provider.account:
        raise ValueError('record state or destination mismatch')
    if normalized.get('id')!=POST or normalized.get('projectId')!=provider.profile: raise ValueError('provider identity mismatch')
    rows=[x for x in normalized.get('socialAccountPosts',[]) if x.get('socialAccountId')==provider.account and x.get('platform')=='youtube' and x.get('deliveryStatus')=='PUBLISHED' and x.get('externalPostId')==VIDEO]
    if len(rows)!=1: raise ValueError('published video mismatch')
    pending=[x for x in snapshot.get('state',{}).get('pending',[]) if str(x.get('post_id'))+':'+str(x.get('media_id'))==key]
    if len(pending)!=1: raise ValueError('source item mismatch')
    ledger=snapshot['ledger']['published_source_ids']
    changed=record.get('state')!='published' or SOURCE not in set(map(str,ledger))
    if SOURCE not in set(map(str,ledger)): ledger.append(SOURCE)
    record.update(state='published',external_post_id=VIDEO,external_post_url='https://www.youtube.com/watch?v='+VIDEO)
    return changed

def main():
    url='https://www.youtube.com/oembed?'+urllib.parse.urlencode({'url':'https://www.youtube.com/watch?v='+VIDEO,'format':'json'})
    with urllib.request.urlopen(url,timeout=20) as r: public=json.load(r)
    verified=public.get('author_name')==CHANNEL and isinstance(public.get('title'),str)
    f=read_key();s=load_snapshot(f);p=ZernioProvider()
    changed=reconcile(s,p,p._api('GET','/posts/'+POST),p.post(POST),verified)
    if changed: encrypted_git_checkpoint(Path(__file__).resolve().parent.parent,f,s)
    print('Existing publication reconciled; no new delivery.' if changed else 'Publication already reconciled.')
if __name__=='__main__':main()
