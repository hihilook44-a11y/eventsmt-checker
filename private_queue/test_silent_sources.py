import unittest,subprocess,tempfile
from datetime import datetime, timezone
from pathlib import Path
from audio_review import has_no_audio_track,verifier_with_silent_sources
from workflow_pipeline import reviewed_candidates
class NoAudio(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.d=tempfile.TemporaryDirectory(); d=Path(cls.d.name)
  def make(name,audio):
   args=['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=64x64:r=10:d=1']
   if audio: args+=['-f','lavfi','-i','sine=frequency=440:duration=1']
   args+=['-c:v','mpeg4'] + (['-c:a','aac','-shortest'] if audio else ['-an']) + [str(d/name)]
   subprocess.run(args,check=True);return (d/name).read_bytes()
  cls.no_audio=make('silent.mp4',False);cls.with_audio=make('sound.mp4',True)
 @classmethod
 def tearDownClass(cls): cls.d.cleanup()
 def test_valid_and_audio_fail_closed(self):
  for d,want in [(self.no_audio,True),(self.with_audio,False),(b'',False),(b'not a video',False)]:self.assertEqual(has_no_audio_track({},d,None),want)
 def test_audio_still_needs_review(self):
  v=verifier_with_silent_sources('');self.assertTrue(v({},self.no_audio,None));self.assertFalse(v({},self.with_audio,None))
 def test_false_not_missing_metadata(self):
  items=[{'post_id':'1','media_id':'2','created_at':datetime.now(timezone.utc).isoformat()},{'post_id':'3','media_id':'4'},{'post_id':'5','media_id':'6'}]
  s={'state':{'pending':items},'ledger':{'published_source_ids':[]},'prepared_media':{'1:2':{'has_audio':False},'3:4':{'has_audio':True},'5:6':{}},'candidate_deliveries':{k:{'state':'awaiting_audio_review'} for k in ('1:2','3:4','5:6')}}
  self.assertEqual(reviewed_candidates(s,verifier_with_silent_sources('')),[items[0]])
if __name__=='__main__':unittest.main()

class DeliveryGate(unittest.TestCase):
 def test_only_exact_silent_file_may_reach_mock_provider(self):
  import copy,hashlib
  from workflow_pipeline import publish_reviewed
  from candidate_pipeline import PipelineError
  from test_reviewed_delivery import Provider
  d=tempfile.TemporaryDirectory()
  try:
   p=Path(d.name)/'clip.mp4'
   subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=64x64:r=10:d=1','-c:v','mpeg4','-an',str(p)],check=True)
   data=p.read_bytes();h=hashlib.sha256(data).hexdigest(); item={'post_id':'12','media_id':'34','text':'test'}; key='12:34'
   snap={'state':{'pending':[item]},'ledger':{'published_source_ids':[]},'prepared_media':{key:{'sha256':h,'has_audio':False}},'candidate_deliveries':{key:{'sha256':h,'state':'awaiting_audio_review'}}}
   provider=Provider(); verify=verifier_with_silent_sources('')
   self.assertEqual(publish_reviewed(snap,lambda s:None,provider,item,data,None,verify,'project','account'),'delivery_recorded')
   self.assertEqual((provider.uploads,provider.posts),(1,1))
   fresh={'state':{'pending':[item]},'ledger':{'published_source_ids':[]},'prepared_media':{key:{'sha256':h,'has_audio':False}},'candidate_deliveries':{key:{'sha256':h,'state':'awaiting_audio_review'}}}
   with self.assertRaises(PipelineError):publish_reviewed(fresh,lambda s:None,provider,item,data+b'x',None,verify,'project','account')
   self.assertEqual((provider.uploads,provider.posts),(1,1))
  finally:d.cleanup()
