import copy,unittest
import candidate_pipeline as cp
from test_candidate_pipeline import ready,DATA
class Tests(unittest.TestCase):
 def test_submit_then_record_only_after_published(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio'); calls=[]
  p.publish_now=lambda *args:(calls.append(args) or 'public-post')
  self.assertEqual(x.publish_now('12:34','account','title','description'),'public-post')
  self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'delivery_recorded');self.assertEqual(st.saved['ledger']['published_source_ids'],[])
  with self.assertRaises(cp.PipelineError):x.reconcile_published('12:34')
  p.post=lambda id:{'id':id,'projectId':'project','socialAccountPosts':[{'socialAccountId':'account','deliveryStatus':'PUBLISHED','externalPostId':'yt'}]}
  self.assertTrue(x.reconcile_published('12:34'));self.assertEqual(st.saved['ledger']['published_source_ids'],['12']);self.assertEqual(len(calls),1)
 def test_timeout_blocks_retry_after_restart(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');calls=[]
  def fail(*args):calls.append(args);raise TimeoutError()
  p.publish_now=fail
  with self.assertRaises(TimeoutError):x.publish_now('12:34','account','title','description')
  self.assertEqual(st.saved['candidate_deliveries']['12:34']['state'],'delivery_uncertain')
  y=cp.CandidatePipeline(copy.deepcopy(st.saved),st.checkpoint,p,lambda *a:True)
  with self.assertRaises(cp.PipelineError):y.publish_now('12:34','account','title','description')
  self.assertEqual(len(calls),1)
 def test_checkpoint_failure_prevents_submission(self):
  x,st,p=ready();x.upload('12:34',DATA,'project','reviewed-exact-audio');st.fail=True;p.publish_now=lambda *a:self.fail('must not submit')
  with self.assertRaises(OSError):x.publish_now('12:34','account','title','description')
 def test_no_review_or_draft_never_publishes(self):
  x,st,p=ready();p.publish_now=lambda *a:self.fail('must not submit')
  with self.assertRaises(cp.PipelineError):x.publish_now('12:34','account','title','description')
  x.upload('12:34',DATA,'project','reviewed-exact-audio');x.draft('12:34','account','title','description')
  with self.assertRaises(cp.PipelineError):x.publish_now('12:34','account','title','description')
if __name__=='__main__':unittest.main()
