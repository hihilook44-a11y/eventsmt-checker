"""Prepare owner-reviewed song-free attestations; never asserts someone listened.

Call only after an authenticated owner response explicitly confirms full listening and
identifies each approved clip. Manifest and source file hashes bind each approval to
the exact reviewed recording. This module never publishes or checkpoints state.
The caller must provision the verification key, encrypt and checkpoint changes using
the existing optimistic-concurrency safeguards; a signature proves only its signer.
"""
import base64,hashlib,re
from pathlib import Path
from audio_review import payload
from candidate_pipeline import _key

class IntakeError(ValueError): pass

def prepare_reviews(manifest,snapshot,media_dir,decisions,owner_message_id,signer):
    if not isinstance(owner_message_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',owner_message_id):
        raise IntakeError('authenticated owner message reference required')
    clips=manifest.get('clips') if isinstance(manifest,dict) else None
    if not isinstance(clips,list) or not clips: raise IntakeError('invalid manifest')
    by_number={}; seen_sources=set()
    for clip in clips:
        if not isinstance(clip,dict): raise IntakeError('invalid clip')
        n=clip.get('number'); source=str(clip.get('source_id','')); digest=clip.get('source_sha256')
        if type(n)!=int or n<1 or n in by_number or not source.isdigit() or source in seen_sources or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise IntakeError('invalid or ambiguous manifest')
        by_number[n]=clip; seen_sources.add(source)
    if not isinstance(decisions,dict) or not decisions: raise IntakeError('explicit review decisions required')
    for n,d in decisions.items():
        if type(n)!=int or n not in by_number or not isinstance(d,dict) or d.get('full_audio_listened') is not True or d.get('verdict') not in ('no_songs','songs','uncertain'):
            raise IntakeError('each decision needs explicit full listening and verdict')
    pending=snapshot.get('state',{}).get('pending')
    if not isinstance(pending,list): raise IntakeError('invalid queue')
    published=set(map(str,snapshot.get('ledger',{}).get('published_source_ids',[])))
    prepared=snapshot.get('prepared_media',{}); deliveries=snapshot.get('candidate_deliveries',{})
    existing=snapshot.get('audio_reviews',{})
    if not all(isinstance(v,dict) for v in (prepared,deliveries,existing)): raise IntakeError('invalid queue records')
    # Stage all changes only after validating every explicitly reviewed item.
    accepted=[]; excluded=[]
    for n,d in decisions.items():
        clip=by_number[n]; source=str(clip['source_id']); digest=clip['source_sha256']
        if d['verdict']!='no_songs': excluded.append(n); continue
        if source in published: raise IntakeError('source already published')
        matches=[item for item in pending if str(item.get('post_id'))==source]
        if len(matches)!=1: raise IntakeError('candidate missing or ambiguous')
        key=_key(matches[0]); p=Path(media_dir)/(source+'.mp4')
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest: raise IntakeError('reviewed file changed or missing')
        if prepared.get(key,{}).get('sha256')!=digest or deliveries.get(key,{}).get('sha256')!=digest or deliveries.get(key,{}).get('state')!='awaiting_audio_review':
            raise IntakeError('queue record does not match reviewed source')
        if key in existing: raise IntakeError('existing review must not be overwritten')
        accepted.append((n,key,digest))
    proofs={}
    for n,key,digest in accepted:
        proofs[key]={'candidate':key,'sha256':digest,'scope':'entire_audio','verdict':'no_songs','signature':base64.b64encode(signer.sign(payload(key,digest))).decode('ascii')}
    return {'proofs':proofs,'approved_numbers':[x[0] for x in accepted], 'excluded_numbers':excluded,'owner_message_id':owner_message_id}
