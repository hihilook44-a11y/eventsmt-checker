#!/usr/bin/env python3
"""Read-only aggregate diagnostics; never print media, identities or queue contents."""
import collections, json, math, os
from candidate_pipeline import _key
from candidate_recency import recent_short
from music_triage import MODEL_VERSION, MAX_DURATION, select
from automatic_audio import proofs
from secure_scan import read_key, load_snapshot

def summarize(s):
    out=collections.Counter()
    prepared=s.get('prepared_media',{}); triage=s.get('music_triage',{}); reviews=s.get('audio_reviews',{}); deliveries=s.get('candidate_deliveries',{})
    published=set(map(str,s['ledger']['published_source_ids'])); approved=proofs(s)
    for item in s['state']['pending']:
        k=_key(item)
        if not recent_short(item): continue
        out['fresh_pending']+=1
        if k.split(':')[0] in published: out['fresh_published']+=1; continue
        out['fresh_unpublished']+=1
        p=prepared.get(k)
        if not isinstance(p,dict): out['fresh_unprepared']+=1; continue
        out['fresh_prepared']+=1
        state=deliveries.get(k,{}).get('state')
        out['delivery_'+(state if state in {'awaiting_audio_review','published','delivery_failed','delivery_scheduled','delivery_uncertain','upload_complete'} else 'other_or_none')]+=1
        if p.get('has_audio') is False: out['fresh_silent']+=1; continue
        if p.get('has_audio') is not True: out['fresh_audio_unknown']+=1; continue
        out['fresh_audio']+=1
        if k in approved: out['fresh_audio_approved']+=1; continue
        if k in reviews: out['fresh_audio_review_present_unusable']+=1; continue
        try:
            dur=float(p.get('duration_seconds'))
            if math.isfinite(dur) and dur>MAX_DURATION: out['fresh_audio_too_long']+=1; continue
        except (ValueError, TypeError): pass
        t=triage.get(k,{})
        if t.get('sha256')!=p.get('sha256') or t.get('model_version')!=MODEL_VERSION:
            out['fresh_audio_unassessed_or_changed']+=1; continue
        cls=t.get('classification')
        out['fresh_audio_'+(cls if cls in {'music_suspected','inconclusive','low_risk'} else 'invalid_result')]+=1
    out['any_assessment_candidate']=int(select(s) is not None)
    return dict(sorted(out.items()))

if __name__=='__main__':
    os.environ['AUTOMATIC_AUDIO_RISK_ACCEPTED']='true'
    print(json.dumps(summarize(load_snapshot(read_key())),sort_keys=True))
