#!/usr/bin/env python3
"""Read-only diagnostics for fresh approved failed Shorts; never retry."""
import os,json,sys,re,urllib.parse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secure_scan import read_key,load_snapshot
from candidate_pipeline import _key
from candidate_recency import recent_short,source_time
from automatic_audio import proofs
from zernio_adapter import ZernioProvider
os.environ['AUTOMATIC_AUDIO_RISK_ACCEPTED']='true'
s=load_snapshot(read_key()); approved=proofs(s); pub=set(map(str,s['ledger']['published_source_ids'])); p=ZernioProvider()
if not p.verify_destination(p.profile,p.account): raise SystemExit('configured destination not connected')
for item in s['state']['pending']:
    k=_key(item); r=s.get('candidate_deliveries',{}).get(k,{})
    if not recent_short(item) or k not in approved or k.split(':')[0] in pub or r.get('state')!='delivery_failed': continue
    post_id=r.get('post_id',''); provider=r.get('provider')
    if provider!='zernio' or not re.fullmatch(r'[0-9a-f]{24}',str(post_id)):
        print(json.dumps({'provider':provider,'fresh':True,'reason':'provider_or_id_not_usable'}));continue
    if r.get('project')!=p.profile or r.get('account')!=p.account:
        print(json.dumps({'post_id':post_id,'reason':'destination_mismatch'}));continue
    normalized=p.post(post_id)
    matching=[v for v in normalized['socialAccountPosts'] if v.get('socialAccountId')==p.account and v.get('platform')=='youtube']
    print(json.dumps({'post_id':post_id,'source_time_utc':source_time(item).isoformat(),'provider':provider,'target_count':len(matching),'delivery_status': matching[0].get('deliveryStatus') if len(matching)==1 else 'unknown','external_post_id': matching[0].get('externalPostId') if len(matching)==1 else None},sort_keys=True))
