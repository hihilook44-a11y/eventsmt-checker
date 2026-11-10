"""Integration of encrypted discovery, verified review and provider receipts.

A caller MUST provide a durable, serialized checkpoint: it must persist the snapshot
remotely before returning and must fail if the remote has changed. It must never rebase
or overwrite a concurrent queue revision. No entry point, scheduler or review authority
is supplied here. A classifier or the presence of an audio track is not a review.
Public delivery is callable only after authenticated audio review and upload.
Uncertain writes block further attempts until reconciled.
"""
import hashlib
import urllib.parse

class PipelineError(ValueError): pass

def _key(item):
    p,m=str(item.get('post_id','')),str(item.get('media_id',''))
    if not p.isdigit() or not m.isdigit(): raise PipelineError('invalid candidate identity')
    return p+':'+m

def _record(snapshot,key):
    rows=snapshot.get('candidate_deliveries',{})
    if not isinstance(rows,dict) or not isinstance(rows.get(key),dict): raise PipelineError('delivery not registered')
    return rows[key]

class CandidatePipeline:
    """A checkpoint commits the entire encrypted snapshot before each mutation.

    review_verifier(item, bytes, proof) must authenticate a completed *whole-audio*
    human review and bind it to these exact bytes. No implementation exists yet.
    Tests inject a verifier; production must fail closed until one is implemented.
    """
    def __init__(self,snapshot,checkpoint,provider,review_verifier=None):
        self.s=snapshot; self.checkpoint=checkpoint; self.provider=provider
        self.review_verifier=review_verifier
        self.poisoned=False

    def _checkpoint(self):
        if self.poisoned: raise PipelineError("checkpoint failed; reload durable state")
        try: self.checkpoint(self.s)
        except Exception:
            self.poisoned=True
            raise

    def _guard(self):
        if self.poisoned: raise PipelineError("checkpoint failed; reload durable state")

    def register(self,key,data):
        self._guard()
        pending=self.s['state']['pending']; ledger=self.s['ledger']['published_source_ids']
        matches=[i for i in pending if _key(i)==key]
        if len(matches)!=1: raise PipelineError('candidate missing or duplicate')
        item=matches[0]; source=key.split(':')[0]
        if source in set(map(str,ledger)): raise PipelineError('source already published')
        if not isinstance(data,bytes) or not data: raise PipelineError('missing bytes')
        digest=hashlib.sha256(data).hexdigest()
        prepared=self.s.get('prepared_media',{}).get(key,{})
        if prepared.get('sha256')!=digest: raise PipelineError('media fingerprint mismatch')
        deliveries=self.s.setdefault('candidate_deliveries',{})
        for k,r in deliveries.items():
            if k!=key and (k.split(':')[0]==source or r.get('sha256')==digest):
                raise PipelineError('duplicate source or media')
        if key in deliveries:
            if deliveries[key].get('sha256')!=digest: raise PipelineError('registered media changed')
            return False
        deliveries[key]={'sha256':digest,'state':'awaiting_audio_review'}
        self._checkpoint()
        return True

    def upload(self,key,data,project,proof):
        self._guard()
        r=_record(self.s,key)
        if r['state']!='awaiting_audio_review': raise PipelineError('state blocks upload or retry')
        if hashlib.sha256(data).hexdigest()!=r['sha256']: raise PipelineError('media fingerprint mismatch')
        source=key.split(':')[0]
        if source in set(map(str,self.s['ledger']['published_source_ids'])): raise PipelineError('source already published')
        items=[i for i in self.s['state']['pending'] if _key(i)==key]
        if len(items)!=1: raise PipelineError('candidate missing or duplicate')
        if not self.review_verifier or not self.review_verifier(items[0],data,proof):
            raise PipelineError('authenticated complete audio review required')
        if not project: raise PipelineError('missing project')
        # This durable checkpoint MUST succeed before invoking the remote write.
        r.update(state='upload_uncertain',project=project,provider=getattr(self.provider,'name','woopsocial'))
        self._checkpoint()
        media=self.provider.upload(project,data)
        if not isinstance(media,str) or not media: raise PipelineError('upload outcome unknown')
        r.update(state='upload_complete',media_id=media)
        self._checkpoint()
        return media

    def draft(self,key,account,title,description):
        self._guard()
        r=_record(self.s,key)
        if r['state']!='upload_complete': raise PipelineError('state blocks draft or retry')
        if not account or not title: raise PipelineError('missing destination or title')
        q=urllib.parse.urlencode({'projectId':r['project'],'mediaId':r['media_id']})
        if hasattr(self.provider,'verify_media'):
            valid=self.provider.verify_media(r['project'],r['media_id'])
        else:
            result=self.provider.call('GET','/media?'+q)
            valid=any(m.get('id')==r['media_id'] and m.get('projectId')==r['project'] for m in result.get('media',[]))
        if not valid: raise PipelineError('uploaded media not verified')
        r.update(state='draft_uncertain',account=account)
        self._checkpoint()
        post=self.provider.draft(account,title,description,r['media_id'])
        if not isinstance(post,str) or not post: raise PipelineError('draft outcome unknown')
        r.update(state='draft_recorded',post_id=post)
        self._checkpoint()
        return post

    def verify_draft(self,key):
        self._guard()
        r=_record(self.s,key)
        if r['state']!='draft_recorded': raise PipelineError('draft id unavailable')
        post=self.provider.post(r['post_id'])
        if post.get('id')!=r['post_id'] or post.get('projectId')!=r['project'] or post.get('schedule',{}).get('type')!='DRAFT':
            raise PipelineError('draft state not established')
        if not any(x.get('socialAccountId')==r['account'] and x.get('deliveryStatus')=='NOT_STARTED' for x in post.get('socialAccountPosts',[])):
            raise PipelineError('draft target or status not established')
        r['state']='verified_draft'; self._checkpoint()
        return True

    def publish_now(self,key,account,title,description):
        """Submit exactly once after verified human audio review and successful upload.

        A draft is not a published post: never submit from a draft state. An uncertain
        create blocks retries until an operator reconciles provider state.
        """
        self._guard()
        r=_record(self.s,key)
        if r['state']!='upload_complete': raise PipelineError('state blocks publish or retry')
        if not account or not title: raise PipelineError('missing destination or title')
        if key.split(':')[0] in set(map(str,self.s['ledger']['published_source_ids'])):
            raise PipelineError('source already published')
        q=urllib.parse.urlencode({'projectId':r['project'],'mediaId':r['media_id']})
        if hasattr(self.provider,'verify_media'):
            valid=self.provider.verify_media(r['project'],r['media_id'])
        else:
            result=self.provider.call('GET','/media?'+q)
            valid=any(m.get('id')==r['media_id'] and m.get('projectId')==r['project'] for m in result.get('media',[]))
        if not valid: raise PipelineError('uploaded media not verified')
        r.update(state='delivery_uncertain',account=account)
        self._checkpoint()
        post=self.provider.publish_now(account,title,description,r['media_id'])
        if not isinstance(post,str) or not post: raise PipelineError('publication outcome unknown')
        r.update(state='delivery_recorded',post_id=post)
        self._checkpoint()
        return post


    def publish_scheduled(self,key,account,title,description,scheduled_for,idempotency_key):
        """Create one scheduled post after exact-byte signed review and durable state."""
        self._guard()
        r=_record(self.s,key)
        if r['state']!='upload_complete': raise PipelineError('state blocks schedule or retry')
        if not account or not title or not scheduled_for or not idempotency_key:
            raise PipelineError('missing scheduled post fields')
        if key.split(':')[0] in set(map(str,self.s['ledger']['published_source_ids'])):
            raise PipelineError('source already published')
        if not hasattr(self.provider,'publish_scheduled'):
            raise PipelineError('provider does not support scheduled posts')
        if hasattr(self.provider,'verify_media'):
            valid=self.provider.verify_media(r['project'],r['media_id'])
        else:
            q=urllib.parse.urlencode({'projectId':r['project'],'mediaId':r['media_id']})
            result=self.provider.call('GET','/media?'+q)
            valid=any(m.get('id')==r['media_id'] and m.get('projectId')==r['project'] for m in result.get('media',[]))
        if not valid: raise PipelineError('uploaded media not verified')
        r.update(state='delivery_uncertain',account=account,scheduled_for=scheduled_for,
                 idempotency_key=idempotency_key,provider=getattr(self.provider,'name','zernio'))
        self._checkpoint()
        post=self.provider.publish_scheduled(account,title,description,r['media_id'],scheduled_for,idempotency_key)
        if not isinstance(post,str) or not post: raise PipelineError('scheduled post outcome unknown')
        r.update(state='delivery_recorded',post_id=post)
        self._checkpoint()
        return post

    def reconcile_published(self,key):
        """Read a known post; record only a provider-confirmed YouTube publication.

        Does not create or publish a post. Unknown post ids cannot be reconciled here.
        """
        self._guard()
        r=_record(self.s,key)
        if r['state'] not in {'draft_recorded','verified_draft','delivery_uncertain','delivery_recorded','delivery_scheduled'} or not r.get('post_id'):
            raise PipelineError('known post required for reconciliation')
        post=self.provider.post(r['post_id'])
        if post.get('id')!=r['post_id'] or post.get('projectId')!=r['project']:
            raise PipelineError('post identity mismatch')
        results=[x for x in post.get('socialAccountPosts',[]) if x.get('socialAccountId')==r['account'] and x.get('deliveryStatus')=='PUBLISHED']
        if len(results)!=1: raise PipelineError('publication not established')
        published=self.s['ledger']['published_source_ids']
        source=key.split(':')[0]
        if source not in set(map(str,published)): published.append(source)
        r['state']='published'
        if results[0].get('externalPostId'):r['external_post_id']=results[0]['externalPostId']
        if results[0].get('externalPostUrl'):r['external_post_url']=results[0]['externalPostUrl']
        self._checkpoint()
        return True
