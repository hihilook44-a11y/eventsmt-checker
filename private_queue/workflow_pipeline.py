#!/usr/bin/env python3
"""Process encrypted candidates with fail-closed, signed whole-audio review.

Audio-bearing candidates require a signed complete review. Unmodified files with
no audio stream may pass an exact-byte probe; no classifier confers approval.
A matching destination and checkpoints remain required before provider writes.
"""
import sys,os,re,hashlib,urllib.parse,json
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT.parent))
from secure_scan import read_key,load_snapshot
from prepare_media import get_media
from candidate_pipeline import CandidatePipeline,PipelineError,_key
from git_checkpoint import encrypted_git_checkpoint
from woopsocial_adapter import Provider
from zernio_adapter import ZernioProvider, ZernioError, stable_idempotency_key
from automatic_audio import verifier as review_verifier, proofs as audio_proofs
from shorts_render import render_short, SHORTS_FORMAT

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
    available=[]
    for item in s['state']['pending']:
        key=_key(item)
        if key in prepared and key.split(':')[0] not in published and key not in deliveries:
            available.append((key,item))
    # Register candidates already eligible for the audio gate first; registration
    # itself cannot upload, and publication still checks exact bytes and destination.
    proofs=audio_proofs(s)
    for key,item in available:
        if key in proofs or prepared[key].get('has_audio') is False:
            return key,item
    return available[0] if available else (None,None)

def _legacy_provider_no_match(name, exc):
    """Only provider-declared bad-ID/not-found responses permit a read-only fallback."""
    text=str(exc)
    if name=='zernio':
        return 'HTTP 404 not_found' in text or 'HTTP 400 invalid_request_error' in text
    if name=='woopsocial':
        return text in {'HTTP 404','HTTP 400'}
    return False


def _resolve_legacy_delivery(record, providers):
    """Resolve an old record with no provider by exact read-only identity checks."""
    found=[]
    for name, candidate in providers.items():
        try:
            post=candidate.post(record['post_id'])
        except Exception as exc:
            if _legacy_provider_no_match(name, exc):
                continue
            raise PipelineError('legacy delivery lookup unavailable') from None
        if post.get('id') != record['post_id']:
            raise PipelineError('legacy post identity mismatch')
        if post.get('projectId') != record.get('project'):
            raise PipelineError('legacy post identity mismatch')
        matches=[v for v in post.get('socialAccountPosts',[]) if v.get('socialAccountId') == record.get('account') and (name != 'zernio' or v.get('platform') == 'youtube')]
        if len(matches)!=1:
            raise PipelineError('legacy post destination mismatch')
        found.append((name,candidate,post,matches[0]))
    if len(found)!=1:
        raise PipelineError('legacy delivery provider unresolved')
    return found[0]


def reconcile_known_deliveries(snapshot,checkpoint,provider,providers=None):
    """Read back known submissions; only confirmed delivery updates the ledger.

    Legacy records without provider metadata are resolved only through read-only
    provider lookups that match the exact post, project and social account. No retry
    occurs for unknown submission IDs or statuses. Ambiguity and transport errors
    stop the workflow rather than interpreting them as absence.
    """
    providers=providers or {getattr(provider,'name','woopsocial'):provider}
    for key,record in list(snapshot.get('candidate_deliveries',{}).items()):
        if record.get('state') not in {'delivery_recorded','delivery_uncertain','delivery_scheduled'} or not record.get('post_id'):
            continue
        raw_provider=record.get('provider')
        selected=providers.get(raw_provider) if raw_provider in {'zernio','woopsocial'} else None
        resolved_legacy=selected is None
        if resolved_legacy:
            selected_name,selected,post,row=_resolve_legacy_delivery(record,providers)
            record['provider']=selected_name
        else:
            selected_name=raw_provider
            post=selected.post(record['post_id'])
            if post.get('id') != record['post_id'] or post.get('projectId') != record.get('project'):
                raise PipelineError('post identity mismatch')
            matches=[v for v in post.get('socialAccountPosts',[]) if v.get('socialAccountId') == record.get('account') and (selected_name != 'zernio' or v.get('platform') == 'youtube')]
            if len(matches)!=1: raise PipelineError('post destination mismatch')
            row=matches[0]
        pipeline=CandidatePipeline(snapshot,checkpoint,selected)
        status=row.get('deliveryStatus')
        if status=='PUBLISHED':
            pipeline.reconcile_published(key)
        elif selected_name=='zernio' and status=='SCHEDULED' and record.get('state')!='delivery_scheduled':
            record['state']='delivery_scheduled'; checkpoint(snapshot)
        elif status=='FAILED' and record.get('state')!='delivery_failed':
            # A provider's definitive failure is not an in-flight submission; mark it
            # so future, independently reviewed candidates aren't blocked forever.
            # This records failure only and never retries or republishes this item.
            record['state']='delivery_failed'; checkpoint(snapshot)
        elif resolved_legacy:
            # Persist the provider only after exact remote identity was established.
            checkpoint(snapshot)
        # NOT_STARTED, SENDING or unknown stay recorded; never retry.


def reconciliation_summary(snapshot):
    """Return a privacy-safe shape/count summary of persisted delivery records."""
    counts={}
    allowed_states={'upload_uncertain','draft_uncertain','delivery_uncertain','delivery_recorded',
                    'delivery_scheduled','delivery_failed','published','awaiting_audio_review','upload_complete','verified_draft'}
    for record in snapshot.get('candidate_deliveries',{}).values():
        if not isinstance(record,dict):
            provider,state,id_shape='other','other','missing'
        else:
            raw_provider=record.get('provider')
            provider=raw_provider if raw_provider in {'zernio','woopsocial'} else 'other'
            raw_state=record.get('state')
            state=raw_state if raw_state in allowed_states else 'other'
            post_id=record.get('post_id')
            if not post_id: id_shape='missing'
            elif isinstance(post_id,str) and re.fullmatch(r'[0-9a-fA-F]{24}',post_id): id_shape='24hex'
            else: id_shape='other'
        key='provider='+provider+' state='+state+' post_id='+id_shape
        counts[key]=counts.get(key,0)+1
    return dict(sorted(counts.items()))

def delivery_in_flight(snapshot):
    """Stop further delivery when an earlier remote write has an unresolved outcome."""
    return any(r.get('state') in {'upload_uncertain','draft_uncertain','delivery_uncertain','delivery_recorded'}
               for r in snapshot.get('candidate_deliveries',{}).values())


def reviewed_candidates(snapshot,verify):
    """Select signed-review candidates or metadata-marked audio-free candidates.

    Metadata never authorizes publishing: an exact-byte verification and saved
    hash match are still required. Uncertain submissions are never advanced.
    """
    if verify is None: return []
    proofs=audio_proofs(snapshot)
    prepared=snapshot.get('prepared_media',{})
    deliveries=snapshot.get('candidate_deliveries',{})
    published=set(map(str,snapshot['ledger']['published_source_ids']))
    return [item for item in snapshot['state']['pending']
            if _key(item).split(':')[0] not in published
            and (_key(item) in proofs or prepared.get(_key(item),{}).get('has_audio') is False)
            and deliveries.get(_key(item),{}).get('state') in ('awaiting_audio_review','upload_complete')]


def exact_destination(provider,project,account):
    if not project or not account: return False
    if hasattr(provider,'verify_destination'):
        return provider.verify_destination(project,account)
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

def zernio_scheduling_enabled(env=None):
    env=os.environ if env is None else env
    return env.get('ZERNIO_SCHEDULED_PUBLISHING_ENABLED','').strip().lower()=='true'


def publish_reviewed(snapshot,checkpoint,provider,item,data,proof,verify,project,account,shorts_renderer=None):
    if getattr(provider,'name','')=='zernio' and not zernio_scheduling_enabled():
        raise PipelineError('Zernio scheduled publishing is disabled')
    key=_key(item)
    if verify is None or not verify(item,data,proof): raise PipelineError('signed complete audio review required')
    if not exact_destination(provider,project,account): raise PipelineError('configured destination unavailable')
    record=snapshot.get('candidate_deliveries',{}).get(key,{})
    if record.get('sha256')!=hashlib.sha256(data).hexdigest(): raise PipelineError('media fingerprint mismatch')
    if key.split(':')[0] in set(map(str,snapshot['ledger']['published_source_ids'])): raise PipelineError('already published')
    pipeline=CandidatePipeline(snapshot,checkpoint,provider,verify)
    if record.get('state')=='awaiting_audio_review': pipeline.upload(key,data,project,proof,render=shorts_renderer)
    elif record.get('state')!='upload_complete': raise PipelineError('state blocks delivery')
    if shorts_renderer is not None and record.get('shorts_format') != SHORTS_FORMAT:
        raise PipelineError('previous upload is not verified Shorts format')
    if record.get('project')!=project: raise PipelineError('uploaded project changed')
    text=re.sub(r'https?://\S+','',str(item.get('text') or ''))
    text=' '.join(text.split())
    title=(text[:80].strip() or 'أحداث MT')+' | أحداث MT'
    description=(text+'\nالمصدر: https://x.com/__eventsMT/status/'+key.split(':')[0]).strip()
    if hasattr(provider,'publish_scheduled'):
        delay=int(os.environ.get('ZERNIO_SCHEDULE_DELAY_MINUTES','15'))
        if not 5 <= delay <= 120: raise PipelineError('scheduled delay outside safe range')
        scheduled=(datetime.now(timezone.utc)+timedelta(minutes=delay)).replace(microsecond=0).isoformat().replace('+00:00','Z')
        idem=stable_idempotency_key(account,key,record['sha256'])
        pipeline.publish_scheduled(key,account,title,description,scheduled,idem)
    else:
        pipeline.publish_now(key,account,title,description)
    reconcile_known_deliveries(snapshot,checkpoint,provider)
    return snapshot['candidate_deliveries'][key]['state']

def recover_uncertain_scheduled(snapshot,checkpoint,provider,verify,now=None):
    """Recover one recent Zernio timeout with the original idempotency key.

    Zernio's documented 24-hour key window guarantees the same key returns the
    original post rather than creating a duplicate. The schedule timestamp must be
    within a conservative 22-hour window: the original job can schedule at most two
    hours after creating the key. Signed review, exact bytes, media and destination
    are rechecked before the request is repeated.
    """
    if getattr(provider,'name','')!='zernio' or verify is None:
        return False
    if not zernio_scheduling_enabled():
        return False
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise PipelineError('recovery clock must be timezone-aware')
    now=now.astimezone(timezone.utc)
    records=snapshot.get('candidate_deliveries',{})
    for key,record in records.items():
        if record.get('state')!='delivery_uncertain' or record.get('provider')!='zernio' or record.get('post_id'):
            continue
        required=('project','account','media_id','scheduled_for','idempotency_key','sha256')
        if any(not record.get(field) for field in required):
            continue
        try:
            scheduled=datetime.fromisoformat(str(record['scheduled_for']).replace('Z','+00:00'))
            if scheduled.tzinfo is None: continue
            scheduled=scheduled.astimezone(timezone.utc)
        except (ValueError,TypeError):
            continue
        age=now-scheduled
        if age>=timedelta(hours=22) or age < -timedelta(hours=2):
            continue
        if (record['project']!=provider.profile or record['account']!=provider.account or
            record['idempotency_key']!=stable_idempotency_key(record['account'],key,record['sha256'])):
            continue
        pending=[item for item in snapshot.get('state',{}).get('pending',[]) if _key(item)==key]
        if len(pending)!=1 or key.split(':')[0] in set(map(str,snapshot.get('ledger',{}).get('published_source_ids',[]))):
            continue
        if not provider.verify_destination(record['project'],record['account']) or not provider.verify_media(record['project'],record['media_id']):
            continue
        item=pending[0]
        data=get_media(item.get('video_url'))
        if not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=record['sha256']:
            continue
        proof=audio_proofs(snapshot).get(key)
        if not verify(item,data,proof):
            continue
        text=re.sub(r'https?://\S+','',str(item.get('text') or ''))
        text=' '.join(text.split())
        title=(text[:80].strip() or 'أحداث MT')+' | أحداث MT'
        description=(text+'\nالمصدر: https://x.com/__eventsMT/status/'+key.split(':')[0]).strip()
        pipeline=CandidatePipeline(snapshot,checkpoint,provider,verify)
        pipeline.retry_scheduled_idempotently(key,record['account'],title,description,record['scheduled_for'],record['idempotency_key'])
        return True
    return False


def main():
    f=read_key();s=load_snapshot(f)
    cp=lambda obj:encrypted_git_checkpoint(ROOT.parent,f,obj)
    print('Persisted delivery summary:', json.dumps(reconciliation_summary(s), sort_keys=True))
    providers={}
    zernio_enabled=zernio_scheduling_enabled()
    if zernio_enabled:
        # Enabling the provider requires an explicit flag plus all three scoped
        # inputs; credentials alone can never activate scheduled publication.
        missing=[name for name in ('ZERNIO_API_KEY','ZERNIO_PROFILE_ID','ZERNIO_YOUTUBE_ACCOUNT_ID')
                 if not os.environ.get(name,'').strip()]
        if missing: raise PipelineError('Zernio enabled but scoped configuration is incomplete')
        provider=ZernioProvider()
        providers['zernio']=provider
        if os.environ.get('WOOPSOCIAL_API_KEY','').strip():
            providers['woopsocial']=Provider()
    else:
        provider=Provider()
        providers['woopsocial']=provider
    if zernio_enabled:
        verifier=review_verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
        if recover_uncertain_scheduled(s,cp,provider,verifier):
            print('Recovered an uncertain scheduled post with its original idempotency key.')
    reconcile_known_deliveries(s,cp,provider,providers)
    if delivery_in_flight(s):
        print('Earlier delivery is unresolved; further publication paused.')
        return
    verify=review_verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
    if getattr(provider,'name','')=='zernio':
        project,account=provider.profile,provider.account
    else:
        project=os.environ.get('WOOPSOCIAL_PROJECT_ID','').strip()
        account=os.environ.get('WOOPSOCIAL_YOUTUBE_ACCOUNT_ID','').strip()
    if not project and not account:
        project,account=established_destination(s,provider)
        print('Saved YouTube destination:', 'matched' if project and account else 'not matched; publication disabled')
    for reviewed in reviewed_candidates(s,verify):
        if not project or not account: break
        reviewed_key=_key(reviewed)
        data=get_media(reviewed['video_url'])
        state=publish_reviewed(s,cp,provider,reviewed,data,audio_proofs(s).get(reviewed_key),verify,project,account,shorts_renderer=render_short)
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
        # Only fixed, pre-approved diagnostics are safe to print. In particular,
        # never surface provider bodies, post text, IDs, URLs or secret values.
        safe_pipeline_errors={
            'post identity mismatch', 'post destination mismatch',
            'publication not established', 'legacy delivery lookup unavailable',
            'legacy post identity mismatch', 'legacy post destination mismatch',
            'legacy delivery provider unresolved', 'configured destination unavailable',
            'saved scheduled attempt does not match recovery',
            'no uncertain scheduled post to recover',
            'idempotent recovery outcome unknown',
            'scheduled post not confirmed', 'scheduled post outcome unknown',
            'earlier delivery is unresolved',
        }
        if isinstance(exc,ZernioError):
            detail=str(exc)
        elif isinstance(exc,PipelineError) and str(exc) in safe_pipeline_errors:
            detail=str(exc)
        else:
            detail=type(exc).__name__
        print('Pipeline stopped safely:',detail,file=sys.stderr);sys.exit(1)
