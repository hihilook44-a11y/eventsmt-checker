#!/usr/bin/env python3
"""Wire encrypted candidate state to draft-only adapter, failing closed on audio.

Production never supplies an audio verifier. This job therefore registers reviewed
bytes only as awaiting review; it does not upload or publish source footage.
All mutations go through an encrypted remote checkpoint; a failure is terminal.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent))
from secure_scan import read_key,load_snapshot
from prepare_media import get_media
from candidate_pipeline import CandidatePipeline,PipelineError,_key
from git_checkpoint import encrypted_git_checkpoint
from woopsocial_adapter import Provider

def run_candidate(snapshot,checkpoint,provider,key,data,project=None,account=None,title=None,description='',proof=None,verifier=None):
    pipeline=CandidatePipeline(snapshot,checkpoint,provider,verifier)
    pipeline.register(key,data)
    if verifier is None:
        return 'awaiting_audio_review'
    pipeline.upload(key,data,project,proof)
    pipeline.draft(key,account,title,description)
    pipeline.verify_draft(key)
    return 'verified_draft'

def select_candidate(s):
    prepared=s.get('prepared_media',{}); deliveries=s.get('candidate_deliveries',{})
    published=set(map(str,s['ledger']['published_source_ids']))
    for item in s['state']['pending']:
        key=_key(item)
        if key in prepared and key.split(':')[0] not in published and key not in deliveries:
            return key,item
    return None,None

def reconcile_known_deliveries(snapshot,checkpoint,provider):
    """Read back known submissions; only confirmed delivery updates the ledger.

    No retry occurs for unknown submission IDs or statuses. Provider/network errors
    stop the workflow rather than interpreting them as absence.
    """
    pipeline=CandidatePipeline(snapshot,checkpoint,provider)
    for key,record in list(snapshot.get('candidate_deliveries',{}).items()):
        if record.get('state') not in {'delivery_recorded','delivery_uncertain'} or not record.get('post_id'):
            continue
        post=provider.post(record['post_id'])
        if post.get('id') != record['post_id'] or post.get('projectId') != record.get('project'):
            raise PipelineError('post identity mismatch')
        matches=[v for v in post.get('socialAccountPosts',[]) if v.get('socialAccountId') == record.get('account')]
        if len(matches)!=1: raise PipelineError('post destination mismatch')
        if matches[0].get('deliveryStatus')=='PUBLISHED':
            pipeline.reconcile_published(key)
        # NOT_STARTED, SENDING, FAILED or unknown stay recorded and never retry.

def main():
    f=read_key();s=load_snapshot(f)
    cp=lambda obj:encrypted_git_checkpoint(ROOT.parent,f,obj)
    provider=Provider()
    reconcile_known_deliveries(s,cp,provider)
    key,item=select_candidate(s)
    if item is None:
        print('No prepared candidate requiring registration.');return
    data=get_media(item['video_url'])
    result=run_candidate(s,cp,provider,key,data)
    print('Candidate registered:',result,'; no upload or publication.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Pipeline stopped safely:',type(exc).__name__,file=sys.stderr);sys.exit(1)
