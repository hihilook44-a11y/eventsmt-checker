#!/usr/bin/env python3
"""Read-only provider reconciliation for one independently confirmed publication.

Never creates posts. A record is updated only when every candidate, destination,
source, media and idempotency key matches the provider's exact post.
"""
import hashlib, json, os, re, sys, urllib.parse, urllib.request
from urllib.parse import urlsplit
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secure_scan import read_key, load_snapshot
from git_checkpoint import encrypted_git_checkpoint
from zernio_adapter import ZernioProvider, stable_idempotency_key
from prepare_media import get_media
from audio_review import verifier_with_silent_sources as review_verifier

POST_ID='6af3574d185f99d035290515'
SOURCE_ID='2119732969342746732'
YOUTUBE_VIDEO_ID='N6qOpOYfI3U'
YOUTUBE_CHANNEL='Mt Fivem- زيكو'

def youtube_video_verified(video_id):
    """Verify the exact public video is served by the intended channel."""
    url='https://www.youtube.com/oembed?'+urllib.parse.urlencode({
        'url':'https://www.youtube.com/watch?v='+video_id,'format':'json'})
    try:
        with urllib.request.urlopen(url,timeout=20) as response:
            if response.status!=200: return False
            payload=json.loads(response.read(200_000))
        return payload.get('author_name')==YOUTUBE_CHANNEL and isinstance(payload.get('title'),str)
    except Exception:
        return False

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

def match_record(snapshot, provider, raw, verify):
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
    pending=[item for item in snapshot.get('state',{}).get('pending',[])
             if str(item.get('post_id',''))+':'+str(item.get('media_id',''))==key]
    if len(pending)!=1:
        raise ValueError('candidate not unique in queue')
    item=pending[0]
    data=get_media(item.get('video_url'))
    if not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('source fingerprint mismatch')
    proof=snapshot.get('audio_reviews',{}).get(key)
    if not verify or not verify(item,data,proof):
        raise ValueError('signed no-songs review not verified')
    if not youtube_video_verified(YOUTUBE_VIDEO_ID):
        raise ValueError('public YouTube video/channel not established')
    # The Zernio GET response for this post omits per-platform results. The exact
    # YouTube video is independently verified through public oEmbed (expected channel),
    # while source, idempotency metadata, uploaded bytes and signed no-songs review above
    # bind that public result to this unique queued candidate.
    return key,record

def main():
    f=read_key(); s=load_snapshot(f); p=ZernioProvider()
    if not p.verify_destination(p.profile,p.account):
        raise ValueError('configured YouTube destination not confirmed')
    raw=p._api('GET','/posts/'+POST_ID)
    verify=review_verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
    key,record=match_record(s,p,raw,verify)
    root=Path(__file__).resolve().parent.parent
    cp=lambda obj:encrypted_git_checkpoint(root,f,obj)
    record.update(state='published',post_id=POST_ID,external_post_id=YOUTUBE_VIDEO_ID,
                  external_post_url='https://www.youtube.com/watch?v='+YOUTUBE_VIDEO_ID)
    published=s['ledger']['published_source_ids']
    if SOURCE_ID not in set(map(str,published)):
        published.append(SOURCE_ID)
    cp(s)
    print('Verified existing YouTube publication; source added to encrypted deduplication ledger.')
if __name__=='__main__': main()
