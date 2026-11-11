import base64,copy,hashlib,unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from audio_review import payload,verifier
from candidate_pipeline import PipelineError
from workflow_pipeline import publish_reviewed,reviewed_candidates
DATA=b'synthetic test media'; KEY='12:34'; ITEM={'post_id':'12','media_id':'34','text':'test'}; H=hashlib.sha256(DATA).hexdigest()
class Provider:
 def __init__(self):self.uploads=0;self.posts=0;self.timeout=False;self.status='NOT_STARTED'
 def projects(self):return [{'id':'project'}]
 def call(self,method,path):
  if path.startswith('/social-accounts?'):return [{'id':'account','platform':'YOUTUBE','status':'CONNECTED'}]
  return {'media':[{'id':'media','projectId':'project'}]}
 def upload(self,project,data):self.uploads+=1;return 'media'
 def publish_now(self,*args):
  self.posts+=1
  if self.timeout:raise TimeoutError('simulated unknown')
  return 'post'
 def post(self,id):return {'id':id,'projectId':'project','socialAccountPosts':[{'socialAccountId':'account','deliveryStatus':self.status}]}
class Tests(unittest.TestCase):
 def setUp(self):
  self.private=Ed25519PrivateKey.generate();self.public=base64.b64encode(self.private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();self.v=verifier(self.public)
  self.proof={'candidate':KEY,'sha256':H,'scope':'entire_audio','verdict':'no_songs','signature':base64.b64encode(self.private.sign(payload(KEY,H))).decode()}
  self.s={'state':{'pending':[ITEM]},'ledger':{'published_source_ids':[]},'prepared_media':{KEY:{'sha256':H}},'candidate_deliveries':{KEY:{'sha256':H,'state':'awaiting_audio_review'}},'audio_reviews':{KEY:self.proof}}
  self.p=Provider();self.saved=copy.deepcopy(self.s)
 def cp(self,s):self.saved=copy.deepcopy(s)
 def run_delivery(self,proof=None,data=DATA):return publish_reviewed(self.s,self.cp,self.p,ITEM,data,proof or self.proof,self.v,'project','account')
 def test_signed_attestation_byte_and_scope_bound(self):
  self.assertTrue(self.v(ITEM,DATA,self.proof));self.assertFalse(self.v(ITEM,b'different',self.proof));bad=dict(self.proof,scope='partial');self.assertFalse(self.v(ITEM,DATA,bad));self.assertFalse(verifier('not a key'))
 def test_publication_only_recorded_after_provider_confirm(self):
  self.assertEqual(self.run_delivery(),'delivery_recorded');self.assertEqual(self.saved['ledger']['published_source_ids'],[]);self.assertEqual((self.p.uploads,self.p.posts),(1,1))
  from workflow_pipeline import reconcile_known_deliveries
  self.p.status='PUBLISHED';reconcile_known_deliveries(self.s,self.cp,self.p)
  self.assertEqual(self.saved['ledger']['published_source_ids'],['12']);self.assertEqual(reviewed_candidates(self.s,self.v),[])
 def test_unknown_submission_blocks_repetition(self):
  self.p.timeout=True
  with self.assertRaises(TimeoutError):self.run_delivery()
  self.assertEqual(self.saved['candidate_deliveries'][KEY]['state'],'delivery_uncertain')
  with self.assertRaises(PipelineError):self.run_delivery()
  self.assertEqual((self.p.uploads,self.p.posts),(1,1));self.assertEqual(reviewed_candidates(self.saved,self.v),[])
 def test_changed_or_unreviewed_bytes_never_upload(self):
  with self.assertRaises(PipelineError):self.run_delivery(data=b'changed')
  bad=dict(self.proof,verdict='no_music_probability_high')
  with self.assertRaises(PipelineError):self.run_delivery(proof=bad)
  self.assertEqual((self.p.uploads,self.p.posts),(0,0));self.assertEqual(reviewed_candidates(self.s,None),[])
 def test_model_result_alone_never_unlocks_publication(self):
  self.s['audio_reviews']={}
  self.s['music_triage']={KEY:{'classification':'inconclusive','sha256':H,'is_clearance':False}}
  self.assertEqual(reviewed_candidates(self.s,self.v),[])
  self.assertEqual((self.p.uploads,self.p.posts),(0,0))
 def test_resume_after_upload_without_reupload(self):
  from candidate_pipeline import CandidatePipeline
  pipeline=CandidatePipeline(self.s,self.cp,self.p,self.v);pipeline.upload(KEY,DATA,'project',self.proof)
  self.assertEqual(self.run_delivery(),'delivery_recorded');self.assertEqual((self.p.uploads,self.p.posts),(1,1))
 def test_destination_mismatch_fails_before_upload(self):
  with self.assertRaises(PipelineError):publish_reviewed(self.s,self.cp,self.p,ITEM,DATA,self.proof,self.v,'project','wrong-account')
  self.assertEqual((self.p.uploads,self.p.posts),(0,0))
if __name__=='__main__':unittest.main()

class DurableIntegration(unittest.TestCase):
 def test_synthetic_delivery_checkpoint_blocks_unknown_replay(self):
  from test_workflow_pipeline import WorkflowTest, git
  from secure_scan import load_snapshot
  fixture=WorkflowTest(methodName='test_full_synthetic_draft_and_remote_checkpoints');fixture.setUp()
  try:
   signer=Ed25519PrivateKey.generate();pub=base64.b64encode(signer.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode();verify=verifier(pub)
   data=fixture.data; key=fixture.key; digest=hashlib.sha256(data).hexdigest();item={'post_id':'12','media_id':'34','text':'synthetic'}
   snap=load_snapshot(fixture.f,fixture.repo/'private_queue'/'queue.enc')
   snap['state']['pending']=[item];snap['candidate_deliveries']={key:{'sha256':digest,'state':'awaiting_audio_review'}}
   proof={'candidate':key,'sha256':digest,'scope':'entire_audio','verdict':'no_songs','signature':base64.b64encode(signer.sign(payload(key,digest))).decode()}
   fixture.cp(snap);p=Provider();p.timeout=True
   with self.assertRaises(TimeoutError):publish_reviewed(snap,fixture.cp,p,item,data,proof,verify,'project','account')
   durable=fixture.saved();self.assertEqual(durable['candidate_deliveries'][key]['state'],'delivery_uncertain');self.assertEqual(durable['ledger']['published_source_ids'],[])
   with self.assertRaises(PipelineError):publish_reviewed(durable,fixture.cp,p,item,data,proof,verify,'project','account')
   self.assertEqual((p.uploads,p.posts),(1,1))
  finally:fixture.tearDown()
