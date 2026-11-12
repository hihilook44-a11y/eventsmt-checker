import hashlib, math, unittest
from copy import deepcopy
from compilation_assessment import assess

class Tests(unittest.TestCase):
 def setUp(self):
  self.data={'1:2':b'file1','3:4':b'file2'}
  self.s={'state':{'pending':[{'post_id':'1','media_id':'2','video_url':'1:2'}, {'post_id':'3','media_id':'4','video_url':'3:4'}]}, 'audio_reviews':{'1:2':{'ok':1},'3:4':{'ok':1}}, 'prepared_media':{k:{'sha256':hashlib.sha256(v).hexdigest()} for k,v in self.data.items()},'ledger':{'published_source_ids':['1']}}
  self.fetch=lambda url:self.data[url]
  self.verify=lambda i,d,p:p=={'ok':1}
  self.probe=lambda d:300.0
 def a(self):return assess(self.s,self.verify,self.fetch,self.probe)
 def test_waits_under_ten_minutes(self):
  self.probe=lambda d:299.9
  self.assertFalse(self.a()['eligible_for_preparation'])
 def test_ten_minutes_ready_but_no_publication_and_short_ledger_independent(self):
  r=self.a();self.assertTrue(r['eligible_for_preparation']);self.assertEqual(r['reviewed_seconds'],600);self.assertFalse(r['publication_performed'])
 def test_unreviewed_is_not_counted(self):
  del self.s['audio_reviews']['3:4'];self.assertEqual(self.a()['reviewed_clips'],1)
 def test_wrong_bytes_are_not_counted(self):
  self.data['1:2']=b'changed';r=self.a();self.assertEqual(r['reviewed_clips'],1);self.assertEqual(r['review_or_media_failures'],1)
 def test_bad_signature_rejected(self):
  self.s['audio_reviews']['1:2']={'ok':0};self.assertEqual(self.a()['reviewed_clips'],1)
 def test_inflight_unknown_blocks_and_is_not_mutated(self):
  self.s['compilation_attempts']={'x':{'state':'delivery_uncertain','source_keys':['9:9'],'source_sha256':['a'*64]}}
  before=deepcopy(self.s);r=self.a();self.assertTrue(r['blocked_by_prior_attempt']);self.assertFalse(r['eligible_for_preparation']);self.assertEqual(before,self.s)
 def test_published_sources_excluded(self):
  self.s['compilation_attempts']={'x':{'state':'published','source_keys':['1:2'],'source_sha256':[hashlib.sha256(b'file1').hexdigest()]}}
  self.assertEqual(self.a()['reviewed_clips'],1)
 def test_published_source_variant_excluded(self):
  self.s['compilation_attempts']={'old':{'state':'published','source_keys':['1:999'],'source_sha256':['a'*64]}}
  self.assertEqual(self.a()['reviewed_clips'],1)
 def test_published_same_bytes_other_identity_excluded(self):
  h=hashlib.sha256(b'file1').hexdigest()
  self.s['compilation_attempts']={'old':{'state':'published','source_keys':['999:999'],'source_sha256':[h]}}
  self.assertEqual(self.a()['reviewed_clips'],1)
 def test_uncertain_never_mutates_or_publishes_on_repeat(self):
  self.s['compilation_attempts']={'x':{'state':'upload_uncertain','source_keys':['9:9'],'source_sha256':['b'*64]}}
  original=deepcopy(self.s)
  for _ in range(2):
   r=self.a();self.assertTrue(r['blocked_by_prior_attempt']);self.assertFalse(r['publication_performed'])
  self.assertEqual(self.s,original)
 def test_unknown_state_blocks(self):
  self.s['compilation_attempts']={'x':{'state':'mystery','source_keys':['1:2'],'source_sha256':[hashlib.sha256(b'file1').hexdigest()]}}
  with self.assertRaises(ValueError):self.a()
 def test_missing_review_key_blocks(self):
  with self.assertRaises(ValueError):assess(self.s,None,self.fetch,self.probe)
 def test_fetch_failure_cannot_count(self):
  self.fetch=lambda url: (_ for _ in ()).throw(TimeoutError())
  self.assertFalse(self.a()['eligible_for_preparation'])
 def test_bad_probe_cannot_count(self):
  self.probe=lambda data:float('nan')
  self.assertFalse(self.a()['eligible_for_preparation'])
 def test_repeat_candidates_rejected(self):
  self.s['state']['pending'].append(dict(self.s['state']['pending'][0]))
  with self.assertRaises(ValueError):self.a()
 def test_attempt_missing_source_list_blocks(self):
  self.s['compilation_attempts']={'x':{'state':'published'}}
  with self.assertRaises(ValueError):self.a()
 def test_low_risk_long_audio_counts_for_compilation_only(self):
  from automatic_audio import verifier,proofs
  from music_triage import MODEL_VERSION
  from unittest.mock import patch
  import os
  k='1:2'; digest=self.s['prepared_media'][k]['sha256']
  proof={'model_version':MODEL_VERSION,'sha256':digest,'classification':'low_risk','is_clearance':False,'assessment_scope':'entire_audio','yamnet_peak':.01,'efficientat_peak':.01,'duration_seconds':219}
  self.s['audio_reviews'].pop(k);self.s['music_triage']={k:proof}
  with patch.dict(os.environ,{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}):
   self.assertNotIn(k,proofs(self.s))
   r=assess(self.s,verifier('',240),self.fetch,lambda _:219)
   self.assertEqual(r['reviewed_clips'],1)
   self.assertEqual(r['reviewed_seconds'],219)
if __name__=='__main__':unittest.main()
