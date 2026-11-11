#!/usr/bin/env python3
"""Scheduled, fail-closed compilation readiness assessment; never uploads or publishes.

Use only explicitly signed complete-audio proofs bound to the exact downloaded bytes.
A distinct compilation ledger is required: Shorts publication is not compilation use.
This assessor never creates or changes a delivery record and deliberately does not
produce a title, thumbnail, render, or provider submission.
"""
import hashlib, json, math, os, subprocess, sys, tempfile
from pathlib import Path
from candidate_pipeline import _key
from compilation_sources import candidates
from automatic_audio import verifier, proofs as audio_proofs
from prepare_media import get_media
from secure_scan import read_key, load_snapshot

MIN_SECONDS = 600.0
BLOCKING = {'upload_uncertain','draft_uncertain','delivery_uncertain','delivery_recorded','delivery_scheduled','published','upload_complete','verified_draft'}

def probe_bytes(data):
    with tempfile.TemporaryDirectory(prefix='compile-assess-') as d:
        os.chmod(d, 0o700)
        p=Path(d)/'input.mp4'; p.write_bytes(data); os.chmod(p, 0o600)
        r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(p)],check=True,capture_output=True,timeout=45)
        details=json.loads(r.stdout); types={s.get('codec_type') for s in details.get('streams',[])}
        duration=float(details['format']['duration'])
        if not math.isfinite(duration) or duration<=0 or not {'video','audio'} <= types: raise ValueError('invalid audio/video')
        return duration

def assess(snapshot, verify, fetch=get_media, probe=probe_bytes, return_plan=False):
    if not callable(verify): raise ValueError('audio verification unavailable')
    items=candidates(snapshot)
    reviews=audio_proofs(snapshot)
    prepared=snapshot.get('prepared_media',{})
    attempts=snapshot.get('compilation_attempts',{})
    if not isinstance(items,list) or not isinstance(reviews,dict) or not isinstance(prepared,dict) or not isinstance(attempts,dict): raise ValueError('invalid snapshot')
    # Do not use ordinary Shorts delivery ledger here: a previously posted Short
    # may be a legitimate part of a separate compilation.
    # Never reconstruct an attempt or interpret a missing receipt as failure.
    active=[]
    for attempt in attempts.values():
        if not isinstance(attempt,dict) or not isinstance(attempt.get('state'),str): raise ValueError('invalid compilation attempt')
        if attempt['state'] not in {'failed_confirmed','abandoned_before_upload'} | BLOCKING: raise ValueError('unknown compilation state')
        if attempt['state'] in BLOCKING: active.append(attempt)
    # A prior ambiguous or scheduled compilation blocks new ones until separately
    # reconciled; this read-only function cannot change or retry an attempt.
    unresolved=any(a['state'] in BLOCKING-{'published'} for a in active)
    used=set(); used_sources=set(); used_hashes=set()
    for a in active:
        keys=a.get('source_keys')
        if not isinstance(keys,list) or not all(isinstance(k,str) and k for k in keys): raise ValueError('attempt source ledger missing')
        hashes=a.get('source_sha256')
        if not isinstance(hashes,list) or len(hashes)!=len(keys) or not all(isinstance(h,str) and len(h)==64 for h in hashes): raise ValueError('attempt fingerprint ledger missing')
        used.update(keys); used_sources.update(k.split(':')[0] for k in keys); used_hashes.update(hashes)
    seen=set(); seen_sources=set(); seen_digests=set(); eligible=[]; errors=0
    for item in items:
        if not isinstance(item,dict): raise ValueError('invalid pending item')
        key=_key(item)
        if key in seen: raise ValueError('duplicate candidate identity')
        seen.add(key)
        if key in used or key.split(':')[0] in used_sources or key not in reviews: continue
        try:
            data=fetch(item['video_url']); digest=hashlib.sha256(data).hexdigest()
            if digest in used_hashes: continue
            if prepared.get(key,{}).get('sha256')!=digest or not verify(item,data,reviews[key]):
                errors+=1; continue
            duration=float(probe(data))
            if not math.isfinite(duration) or duration<=0: raise ValueError('invalid duration')
            source=key.split(':')[0]
            if source in seen_sources or digest in seen_digests: raise ValueError('duplicate source or media')
            seen_sources.add(source); seen_digests.add(digest)
            eligible.append({'key':key,'sha256':digest,'duration_seconds':duration})
        except Exception:
            errors+=1
    seconds=sum(r['duration_seconds'] for r in eligible)
    # Errors are non-clearance and never count as usable time. This assessment
    # contains no source identifiers or links, keeping workflow logs private.
    result = {'reviewed_clips':len(eligible),'reviewed_seconds':round(seconds,3),
            'eligible_for_preparation':not unresolved and seconds>=MIN_SECONDS,
            'blocked_by_prior_attempt':unresolved,'review_or_media_failures':errors,
            'publication_performed':False,'mode':'assessment_only'}
    return (result, eligible) if return_plan else result

def main():
    pub=os.environ.get('AUDIO_REVIEW_PUBLIC_KEY','')
    verify=verifier(pub)
    result=assess(load_snapshot(read_key()),verify)
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Compilation assessment stopped safely: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
