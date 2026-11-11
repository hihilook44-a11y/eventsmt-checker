import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from shorts_render import render_short,SHORTS_FORMAT
from candidate_pipeline import CandidatePipeline,PipelineError
class Tests(unittest.TestCase):
 def test_portrait_keeps_audio_and_full_duration(self):
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'in.mp4'; b=Path(d)/'out.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=15:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-c:a','aac','-shortest',str(a)],check=True)
   b.write_bytes(render_short(a.read_bytes()))
   def probe(p): return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,codec_name,width,height','-of','json',str(p)]))
   s=probe(a); out=probe(b); vid=next(x for x in out['streams'] if x['codec_type']=='video')
   self.assertEqual((vid['width'],vid['height']),(720,1280));self.assertLess(abs(float(out['format']['duration'])-float(s['format']['duration'])),.25)
   # An unchanged AAC bitstream proves the original audio survived remuxing.
   def audio(p):return subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-map','0:a:0','-c','copy','-f','adts','pipe:1'])
   self.assertEqual(audio(a),audio(b))
 def test_bad_bytes_fail_before_upload(self):
  item={'post_id':'1','media_id':'2'}; data=b'invalid'; dig=hashlib.sha256(data).hexdigest(); snap={'state':{'pending':[item]},'ledger':{'published_source_ids':[]},'candidate_deliveries':{'1:2':{'sha256':dig,'state':'awaiting_audio_review'}}}
  class Provider:
   def upload(self,*a):raise AssertionError('must not upload')
  p=CandidatePipeline(snap,lambda s:None,Provider(),lambda *a:True)
  with self.assertRaises(Exception):p.upload('1:2',data,'p',{},render_short)
  self.assertEqual(snap['candidate_deliveries']['1:2']['state'],'awaiting_audio_review')
 def test_verified_before_render(self):
  item={'post_id':'1','media_id':'2'}; data=b'x'; dig=hashlib.sha256(data).hexdigest(); snap={'state':{'pending':[item]},'ledger':{'published_source_ids':[]},'candidate_deliveries':{'1:2':{'sha256':dig,'state':'awaiting_audio_review'}}}
  class Provider:
   def upload(self,*a):raise AssertionError('must not upload')
  def render(_):raise AssertionError('must not render')
  p=CandidatePipeline(snap,lambda s:None,Provider(),lambda *a:False)
  with self.assertRaises(PipelineError):p.upload('1:2',data,'p',{},render)
 def test_upload_receives_rendered_bytes_after_audio_verification(self):
  item={'post_id':'1','media_id':'2'}; original=b'original'; dig=hashlib.sha256(original).hexdigest(); snap={'state':{'pending':[item]},'ledger':{'published_source_ids':[]},'candidate_deliveries':{'1:2':{'sha256':dig,'state':'awaiting_audio_review'}}}; snapshots=[]
  class Provider:
   name='zernio'
   def upload(self,p,data):
    assert snapshots[-1]['state']=='upload_uncertain' and data==b'vertical video'
    return 'media'
  import copy
  cp=CandidatePipeline(snap,lambda s:snapshots.append(copy.deepcopy(s['candidate_deliveries']['1:2'])),Provider(),lambda i,d,p:d==original)
  cp.upload('1:2',original,'p',{},lambda d:b'vertical video')
  self.assertEqual(snap['candidate_deliveries']['1:2']['sha256'],dig)
  self.assertEqual(snap['candidate_deliveries']['1:2']['upload_sha256'],hashlib.sha256(b'vertical video').hexdigest())
  self.assertEqual(snap['candidate_deliveries']['1:2']['shorts_format'],SHORTS_FORMAT)
