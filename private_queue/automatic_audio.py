"""Explicitly enabled probabilistic audio policy; never a human review or guarantee.

Uses only exact-byte whole-track model assessments. The owner accepted detector
false negatives on 2026-11-11. Errors/suspicion/missing evidence remain blocked.
"""
import hashlib, math, os
from music_triage import MODEL_VERSION
LIMIT=0.05

def enabled():
    return os.environ.get('AUTOMATIC_AUDIO_RISK_ACCEPTED','').lower()=='true'

def low_risk(proof, digest):
    if not enabled() or not isinstance(proof,dict): return False
    if proof.get('model_version')!=MODEL_VERSION or proof.get('sha256')!=digest: return False
    if proof.get('classification')!='low_risk' or proof.get('is_clearance') is not False: return False
    if proof.get('assessment_scope')!='entire_audio': return False
    try:
        scores=[float(proof[k]) for k in ('yamnet_peak','efficientat_peak')]
        duration=float(proof['duration_seconds'])
        return all(math.isfinite(v) and 0<=v<LIMIT for v in scores) and math.isfinite(duration) and 0<duration<=180
    except (KeyError,ValueError,TypeError):return False

def proofs(snapshot):
    result=dict(snapshot.get('audio_reviews',{}))
    if enabled():
        for key,value in snapshot.get('music_triage',{}).items():
            digest=snapshot.get('prepared_media',{}).get(key,{}).get('sha256')
            if key not in result and low_risk(value,digest):result[key]=dict(value)
    return result

def verifier(public_key_b64):
    from audio_review import verifier_with_silent_sources
    human=verifier_with_silent_sources(public_key_b64)
    def verify(item,data,proof):
        return human(item,data,proof) or low_risk(proof,hashlib.sha256(data).hexdigest())
    return verify
