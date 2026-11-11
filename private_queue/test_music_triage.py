import unittest,hashlib
from copy import deepcopy
from music_triage import triage_one,select,MODEL_VERSION
class Tests(unittest.TestCase):
 def setUp(self):
  self.data=b'correct';self.key='1:2';self.s={'ledger':{'published_source_ids':[]},'state':{'pending':[{'post_id':'1','media_id':'2','video_url':'fake'}]},'prepared_media':{self.key:{'has_audio':True,'sha256':hashlib.sha256(self.data).hexdigest()}}}
  self.fetch=lambda u:self.data
  self.score=lambda d:{'classification':'inconclusive','yamnet_peak':0.01,'efficientat_peak':0.02,'duration_seconds':5}
 def test_inconclusive_is_never_clearance_and_does_not_mutate_reviews(self):
  self.assertTrue(triage_one(self.s,self.fetch,self.score));r=self.s['music_triage'][self.key];self.assertFalse(r['is_clearance']);self.assertNotIn('audio_reviews',self.s);self.assertNotIn('candidate_deliveries',self.s)
 def test_music_suspected_is_not_clearance(self):
  self.assertTrue(triage_one(self.s,self.fetch,lambda d:{'classification':'music_suspected'}));self.assertFalse(self.s['music_triage'][self.key]['is_clearance'])
 def test_changed_bytes_rejected(self):
  self.s['prepared_media'][self.key]['sha256']='0'*64;before=deepcopy(self.s)
  with self.assertRaises(ValueError):triage_one(self.s,self.fetch,self.score)
  self.assertEqual(before,self.s)
 def test_score_failure_leaves_state_intact(self):
  before=deepcopy(self.s)
  def error(d):raise RuntimeError()
  with self.assertRaises(RuntimeError):triage_one(self.s,self.fetch,error)
  self.assertEqual(before,self.s)
 def test_prohibit_clear_classification(self):
  with self.assertRaises(ValueError):triage_one(self.s,self.fetch,lambda d:{'classification':'no_songs'})
  self.assertNotIn('music_triage',self.s)
 def test_idempotent_on_same_digest_and_version(self):
  triage_one(self.s,self.fetch,self.score);before=deepcopy(self.s);self.assertFalse(triage_one(self.s,self.fetch,self.score));self.assertEqual(before,self.s)
 def test_published_reviewed_and_silent_excluded(self):
  self.s['ledger']['published_source_ids']=['1'];self.assertIsNone(select(self.s));self.s['ledger']['published_source_ids']=[]
  self.s['audio_reviews']={self.key:{}};self.assertIsNone(select(self.s));self.s['audio_reviews']={};self.s['prepared_media'][self.key]['has_audio']=False;self.assertIsNone(select(self.s))
 def test_other_models_reassessed(self):
  self.s['music_triage']={self.key:{'sha256':self.s['prepared_media'][self.key]['sha256'],'model_version':'old'}};self.assertTrue(triage_one(self.s,self.fetch,self.score))
if __name__=='__main__':unittest.main()
