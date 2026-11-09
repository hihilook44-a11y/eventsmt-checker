import base64,hashlib,tempfile,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from audio_review import verifier
from review_intake import prepare_reviews,IntakeError

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name); self.data=b'original file';(self.dir/'123.mp4').write_bytes(self.data)
  self.digest=hashlib.sha256(self.data).hexdigest();self.item={'post_id':'123','media_id':'456'};self.key='123:456'
  self.man={'clips':[{'number':1,'source_id':'123','source_sha256':self.digest}]}
  self.snap={'state':{'pending':[self.item]},'ledger':{'published_source_ids':[]},'prepared_media':{self.key:{'sha256':self.digest}},'candidate_deliveries':{self.key:{'sha256':self.digest,'state':'awaiting_audio_review'}}}
  self.signer=Ed25519PrivateKey.generate(); self.decision={1:{'full_audio_listened':True,'verdict':'no_songs'}}
 def tearDown(self): self.tmp.cleanup()
 def make(self,decisions=None,msg='owner-message-1'): return prepare_reviews(self.man,self.snap,self.dir,self.decision if decisions is None else decisions,msg,self.signer)
 def test_signed_exact_bytes(self):
  r=self.make(); raw=self.signer.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
  v=verifier(base64.b64encode(raw).decode()); proof=r['proofs'][self.key];self.assertTrue(v(self.item,self.data,proof));self.assertFalse(v(self.item,self.data+b'x',proof));self.assertNotIn('audio_reviews',self.snap)
 def test_full_review_must_be_explicit(self):
  for d in ({1:{'verdict':'no_songs'}},{1:{'full_audio_listened':False,'verdict':'no_songs'}},{}):
   with self.assertRaises(IntakeError):self.make(d)
 def test_songs_or_uncertainty_never_cleared(self):
  for verdict in ('songs','uncertain'):
   r=self.make({1:{'full_audio_listened':True,'verdict':verdict}});self.assertEqual(r['proofs'],{});self.assertEqual(r['excluded_numbers'],[1])
 def test_modified_file_rejected(self):
  (self.dir/'123.mp4').write_bytes(b'changed')
  with self.assertRaises(IntakeError):self.make()
 def test_queue_state_mismatch_rejected(self):
  self.snap['candidate_deliveries'][self.key]['state']='upload_uncertain'
  with self.assertRaises(IntakeError):self.make()
 def test_unknown_numbers_and_missing_source_rejected(self):
  with self.assertRaises(IntakeError):self.make({2:{'full_audio_listened':True,'verdict':'no_songs'}})
  self.snap['state']['pending']=[]
  with self.assertRaises(IntakeError):self.make()
 def test_missing_owner_reference_rejected(self):
  with self.assertRaises(IntakeError):self.make(msg='')
 def test_duplicate_source_and_replay_rejected(self):
  self.man['clips'].append({'number':2,'source_id':'123','source_sha256':self.digest})
  with self.assertRaises(IntakeError):self.make()
  self.man['clips'].pop();self.snap['audio_reviews']={self.key:{}}
  with self.assertRaises(IntakeError):self.make()
if __name__=='__main__':unittest.main()
