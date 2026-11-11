import unittest,os,hashlib
from unittest.mock import patch
from automatic_audio import low_risk,proofs,verifier
from music_triage import MODEL_VERSION
class Tests(unittest.TestCase):
 def setUp(self):
  self.data=b'media';self.digest=hashlib.sha256(self.data).hexdigest()
  self.p={'model_version':MODEL_VERSION,'sha256':self.digest,'classification':'low_risk','is_clearance':False,'assessment_scope':'entire_audio','yamnet_peak':.01,'efficientat_peak':.02,'duration_seconds':12}
 def test_requires_explicit_policy(self):
  with patch.dict(os.environ,{},clear=True):self.assertFalse(low_risk(self.p,self.digest))
 def test_enabled_exact_bytes(self):
  with patch.dict(os.environ,{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}):
   self.assertTrue(low_risk(self.p,self.digest));self.assertFalse(low_risk(self.p,'0'*64));self.assertTrue(verifier('')({},self.data,self.p))
 def test_bad_scores_and_scope_block(self):
  with patch.dict(os.environ,{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}):
   for k,v in [('yamnet_peak',.05),('efficientat_peak',float('nan')),('duration_seconds',181),('classification','inconclusive'),('assessment_scope','sample'),('model_version','old'),('is_clearance',True)]:
    p={**self.p,k:v};self.assertFalse(low_risk(p,self.digest),(k,v))
 def test_no_human_review_mutation(self):
  s={'music_triage':{'1:2':self.p},'prepared_media':{'1:2':{'sha256':self.digest}},'audio_reviews':{}}
  with patch.dict(os.environ,{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}):self.assertIn('1:2',proofs(s))
  self.assertEqual(s['audio_reviews'],{})
if __name__=='__main__':unittest.main()
