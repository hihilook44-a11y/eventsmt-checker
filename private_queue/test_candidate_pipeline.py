import copy,hashlib,unittest
import candidate_pipeline as cp
DATA=b'test video bytes'
H=hashlib.sha256(DATA).hexdigest()
def snapshot(): return {'state':{'pending':[{'post_id':'12','media_id':'34'}]},'ledger':{'published_source_ids':[]},'prepared_media':{'12:34':{'sha256':H}}}
class Store:
 def __init__(self,s):self.saved=copy.deepcopy(s);self.calls=0;self.fail=False
 def checkpoint(self,s):
  self.calls+=1
  if self.fail:raise OSError('checkpoint failed')
  self.saved=copy.deepcopy(s)
class Provider:
 def __init__(self):self.uploads=0;self.drafts=0;self.upload_error=False;self.draft_error=False
 def upload(self,project,data):
  self.uploads+=1
  if self.upload_error:raise TimeoutError()
  return 'media'
 def call(self,method,path):return {'media':[{'id':'media','projectId':'project'}]}
 def draft(self,account,title,desc,media):
  self.drafts+=1
  if self.draft_error:raise TimeoutError()
  return 'post'
 def post(self,id):return {'id':id,'projectId':'project','schedule':{'type':'DRAFT'},'socialAccountPosts':[{'socialAccountId':'account','deliveryStatus':'NOT_STARTED'}]}
def ready():
 s=snapshot();st=Store(s);p=Provider();x=cp.CandidatePipeline(s,st.checkpoint,p,lambda i,d,proof:proof=='reviewed-exact-audio');x.register('12:34',DATA);return x,st,p
class Tests(unittest.TestCase):
 def test_full_draft_only_and_duplicate(self):
  x,st,p=ready(); self.assertFalse(x.register('12:34',DATA));x.upload('12:34',DATA,'project','reviewed-exact-audio'); x.draft('12:34','account','title','description'); self.assertTrue(x.verify_draft('12:34')); self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'verified_draft');self.assertEqual((p.uploads,p.drafts),(1,1));self.assertEqual(st.saved['ledger']['published_source_ids'],[])
  with self.assertRaises(cp.PipelineError):x.upload('12:34',DATA,'project','reviewed-exact-audio')
 def test_no_reviewer_no_upload(self):
  x,st,p=ready();x.review_verifier=None
  with self.assertRaises(cp.PipelineError):x.upload('12:34',DATA,'project',None)
  self.assertEqual(p.uploads,0);self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'awaiting_audio_review')
 def test_checkpoint_failure_before_upload(self):
  x,st,p=ready();st.fail=True
  with self.assertRaises(OSError):x.upload('12:34',DATA,'project','reviewed-exact-audio')
  self.assertEqual(p.uploads,0);self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'awaiting_audio_review')
 def test_post_upload_checkpoint_failure_leaves_unknown_remotely(self):
  x,st,p=ready()
  original=p.upload
  def upload(project,data):
   value=original(project,data);st.fail=True;return value
  p.upload=upload
  with self.assertRaises(OSError):x.upload('12:34',DATA,'project','reviewed-exact-audio')
  self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'upload_uncertain')
  with self.assertRaises(cp.PipelineError):x.draft('12:34','account','title','description')
  self.assertEqual((p.uploads,p.drafts),(1,0))
 def test_no_draft_if_checkpoint_fails(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');st.fail=True
  with self.assertRaises(OSError):x.draft('12:34','account','title','description')
  self.assertEqual(p.drafts,0);self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'upload_complete')
 def test_upload_timeout_prevents_repeat_after_restart(self):
  x,st,p=ready();p.upload_error=True
  with self.assertRaises(TimeoutError):x.upload('12:34',DATA,'project','reviewed-exact-audio')
  self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'upload_uncertain')
  y=cp.CandidatePipeline(copy.deepcopy(st.saved),st.checkpoint,p,lambda *a:True)
  with self.assertRaises(cp.PipelineError):y.upload('12:34',DATA,'project','reviewed-exact-audio')
  self.assertEqual(p.uploads,1)
 def test_draft_timeout_prevents_repeat(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');p.draft_error=True
  with self.assertRaises(TimeoutError):x.draft('12:34','account','title','description')
  self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'draft_uncertain')
  y=cp.CandidatePipeline(copy.deepcopy(st.saved),st.checkpoint,p,lambda *a:True)
  with self.assertRaises(cp.PipelineError):y.draft('12:34','account','title','description')
  self.assertEqual(p.drafts,1)
 def test_already_published_and_wrong_hash(self):
  s=snapshot();s['ledger']['published_source_ids']=['12'];x=cp.CandidatePipeline(s,lambda s:None,Provider())
  with self.assertRaises(cp.PipelineError):x.register('12:34',DATA)
  s=snapshot();x=cp.CandidatePipeline(s,lambda s:None,Provider())
  with self.assertRaises(cp.PipelineError):x.register('12:34',b'changed')
 def test_duplicate_media_across_sources(self):
  s=snapshot();s['state']['pending'].append({'post_id':'56','media_id':'78'});s['prepared_media']['56:78']={'sha256':H};x=cp.CandidatePipeline(s,lambda s:None,Provider());x.register('12:34',DATA)
  with self.assertRaises(cp.PipelineError):x.register('56:78',DATA)
 def test_draft_not_publication(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');x.draft('12:34','account','title','description');x.verify_draft('12:34');self.assertEqual(x.s['ledger']['published_source_ids'],[])
 def test_record_published_only_when_provider_confirms(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');x.draft('12:34','account','title','description');x.verify_draft('12:34')
  with self.assertRaises(cp.PipelineError):x.reconcile_published('12:34')
  self.assertEqual(st.saved['ledger']['published_source_ids'],[])
  p.post=lambda id:{'id':id,'projectId':'project','socialAccountPosts':[{'socialAccountId':'account','deliveryStatus':'PUBLISHED','externalPostId':'yt-id'}]}
  self.assertTrue(x.reconcile_published('12:34'));self.assertEqual(st.saved['ledger']['published_source_ids'],['12']);self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'published')
 def test_wrong_account_never_marks_published(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');x.draft('12:34','account','title','description')
  p.post=lambda id:{'id':id,'projectId':'project','socialAccountPosts':[{'socialAccountId':'other','deliveryStatus':'PUBLISHED'}]}
  with self.assertRaises(cp.PipelineError):x.reconcile_published('12:34')
  self.assertEqual(st.saved['ledger']['published_source_ids'],[])
 def test_draft_missing_media_refuses(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');p.call=lambda *a:{'media':[]}
  with self.assertRaises(cp.PipelineError):x.draft('12:34','account','title','description')
  self.assertEqual(p.drafts,0);self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'upload_complete')
if __name__=='__main__':unittest.main()
