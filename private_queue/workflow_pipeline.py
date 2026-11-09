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

def main():
    f=read_key();s=load_snapshot(f);key,item=select_candidate(s)
    if item is None:
        print('No prepared candidate requiring registration.');return
    data=get_media(item['video_url'])
    cp=lambda obj:encrypted_git_checkpoint(ROOT.parent,f,obj)
    result=run_candidate(s,cp,Provider(),key,data)
    print('Candidate registered:',result,'; no upload or publication.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Pipeline stopped safely:',type(exc).__name__,file=sys.stderr);sys.exit(1)
