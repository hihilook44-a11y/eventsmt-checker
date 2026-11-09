#!/usr/bin/env python3
"""Process encrypted candidates with fail-closed, signed whole-audio review.

Without an independently provisioned review key, signed evidence, and an exact
configured destination, this only registers candidates for review. No automatic
audio analysis can confer approval. Checkpoints precede all provider writes.
"""
import sys,os,re,hashlib,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent))
from secure_scan import read_key,load_snapshot
from prepare_media import get_media
from candidate_pipeline import CandidatePipeline,PipelineError,_key
from git_checkpoint import encrypted_git_checkpoint
from woopsocial_adapter import Provider
from audio_review import verifier as review_verifier

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


def reviewed_candidates(snapshot,verify):
    """Yield only candidates with authentic, byte-bound review evidence.

    Do not download or advance any other records, including uncertain submissions.
    """
    if verify is None: return []
    proofs=snapshot.get('audio_reviews',{})
    deliveries=snapshot.get('candidate_deliveries',{})
    published=set(map(str,snapshot['ledger']['published_source_ids']))
    return [item for item in snapshot['state']['pending']
            if _key(item).split(':')[0] not in published
            and _key(item) in proofs
            and deliveries.get(_key(item),{}).get('state') in ('awaiting_audio_review','upload_complete')]


def exact_destination(provider,project,account):
    if not project or not account: return False
    projects=provider.projects()
    if sum(1 for p in projects if p.get('id')==project)!=1: return False
    rows=provider.call('GET','/social-accounts?'+urllib.parse.urlencode({'projectId':project}))
    return sum(1 for r in rows if r.get('id')==account and r.get('platform')=='YOUTUBE' and r.get('status')=='CONNECTED')==1


def established_destination(snapshot, provider):
    """Reuse a successful draft-test target only if it still names the requested channel."""
    r=snapshot.get('integration_test',{})
    if r.get('state')!='verified_draft': return None,None
    project,account=r.get('project'),r.get('account')
    if not project or not account: return None,None
    projects=provider.projects()
    if sum(1 for p in projects if p.get('id')==project)!=1: return None,None
    rows=provider.call('GET','/social-accounts?'+urllib.parse.urlencode({'projectId':project}))
    matches=[r for r in rows if r.get('id')==account and r.get('platform')=='YOUTUBE' and r.get('status')=='CONNECTED']
    if len(matches)!=1: return None,None
    name=' '.join(str(matches[0].get('username','')).casefold().split())
    if name!='mt fivem- زيكو': return None,None
    return project,account

def publish_reviewed(snapshot,checkpoint,provider,item,data,proof,verify,project,account):
    key=_key(item)
    if verify is None or not verify(item,data,proof): raise PipelineError('signed complete audio review required')
    if not exact_destination(provider,project,account): raise PipelineError('configured destination unavailable')
    record=snapshot.get('candidate_deliveries',{}).get(key,{})
    if record.get('sha256')!=hashlib.sha256(data).hexdigest(): raise PipelineError('media fingerprint mismatch')
    if key.split(':')[0] in set(map(str,snapshot['ledger']['published_source_ids'])): raise PipelineError('already published')
    pipeline=CandidatePipeline(snapshot,checkpoint,provider,verify)
    if record.get('state')=='awaiting_audio_review': pipeline.upload(key,data,project,proof)
    elif record.get('state')!='upload_complete': raise PipelineError('state blocks delivery')
    if record.get('project')!=project: raise PipelineError('uploaded project changed')
    text=re.sub(r'https?://\S+','',str(item.get('text') or ''))
    text=' '.join(text.split())
    title=(text[:80].strip() or 'أحداث MT')+' | أحداث MT'
    description=(text+'\nالمصدر: https://x.com/__eventsMT/status/'+key.split(':')[0]).strip()
    pipeline.publish_now(key,account,title,description)
    reconcile_known_deliveries(snapshot,checkpoint,provider)
    return snapshot['candidate_deliveries'][key]['state']

def main():
    f=read_key();s=load_snapshot(f)
    cp=lambda obj:encrypted_git_checkpoint(ROOT.parent,f,obj)
    provider=Provider()
    reconcile_known_deliveries(s,cp,provider)
    verify=review_verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
    project=os.environ.get('WOOPSOCIAL_PROJECT_ID','').strip()
    account=os.environ.get('WOOPSOCIAL_YOUTUBE_ACCOUNT_ID','').strip()
    if not project and not account:
        project,account=established_destination(s,provider)
        print('Saved YouTube destination:', 'matched' if project and account else 'not matched; publication disabled')
    for reviewed in reviewed_candidates(s,verify):
        if not project or not account: break
        reviewed_key=_key(reviewed)
        data=get_media(reviewed['video_url'])
        state=publish_reviewed(s,cp,provider,reviewed,data,s['audio_reviews'][reviewed_key],verify,project,account)
        print('Reviewed candidate submitted; delivery state:',state)
        return
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
