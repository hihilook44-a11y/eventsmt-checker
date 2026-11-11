import copy, hashlib, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from compilation_delivery import Delivery,choose_plan,metadata,render,sha,unused_rows

class Provider:
 profile='project';account='account'
 def __init__(self):self.calls=[];self.status='SCHEDULED'
 def verify_destination(self,*a):return True
 def upload(self,*a,**k):self.calls.append('video');return 'video-url'
 def verify_media(self,*a):return True
 def upload_image(self,*a):self.calls.append('image');return 'image-url'
 def publish_compilation(self,*a):self.calls.append('post');return 'post-id'
 def post(self,*a):return {'id':'post-id','projectId':self.profile,'socialAccountPosts':[{'platform':'youtube','socialAccountId':self.account,'deliveryStatus':self.status}]}

class Tests(unittest.TestCase):
 def setUp(self):
  self.s={};self.p=Provider();self.saved=[]
  self.d=Delivery(self.s,lambda s:self.saved.append(copy.deepcopy(s)),self.p)
  self.plan=[{'key':'1:1','sha256':'a'*64,'duration_seconds':600}]
  self.details={'title':'title','description':'sources','duration_seconds':600,'video_sha256':sha(b'video'),'thumbnail_sha256':sha(b'image')}
 def submit(self):return self.d.submit(self.plan,self.details,b'video',b'image')
 def test_schedule_has_durable_checkpoints_before_each_effect(self):
  self.p.upload=lambda *a,**k:self.assertEqual(list(self.saved[-1]['compilation_attempts'].values())[0]['state'],'upload_uncertain') or 'video-url'
  self.p.upload_image=lambda *a:self.assertIn('media_url',list(self.saved[-1]['compilation_attempts'].values())[0]) or 'image-url'
  self.p.publish_compilation=lambda *a:self.assertEqual(list(self.saved[-1]['compilation_attempts'].values())[0]['state'],'delivery_uncertain') or 'post-id'
  self.assertEqual(self.submit(),'delivery_scheduled')
 def test_scheduled_attempt_is_not_repeated(self):
  self.submit();calls=self.p.calls[:]
  with self.assertRaisesRegex(ValueError,'unresolved'):self.submit()
  self.assertEqual(calls,self.p.calls)
 def test_upload_uncertainty_blocks_retry(self):
  self.p.upload=lambda *a,**k:(_ for _ in ()).throw(TimeoutError())
  with self.assertRaises(TimeoutError):self.submit()
  with self.assertRaisesRegex(ValueError,'unresolved'):self.submit()
 def test_thumbnail_uncertainty_blocks_retry(self):
  self.p.upload_image=lambda *a:(_ for _ in ()).throw(TimeoutError())
  with self.assertRaises(TimeoutError):self.submit()
  with self.assertRaisesRegex(ValueError,'unresolved'):self.submit()
  self.assertEqual(self.p.calls,['video'])
 def test_submission_uncertainty_blocks_retry(self):
  self.p.publish_compilation=lambda *a:(_ for _ in ()).throw(TimeoutError())
  with self.assertRaises(TimeoutError):self.submit()
  with self.assertRaisesRegex(ValueError,'unresolved'):self.submit()
 def test_checkpoint_failure_means_no_upload(self):
  self.d.cp=lambda s:(_ for _ in ()).throw(RuntimeError())
  with self.assertRaises(RuntimeError):self.submit()
  self.assertFalse(self.p.calls)
  with self.assertRaisesRegex(ValueError,'reload'):self.submit()
 def test_exact_bytes_required(self):
  self.details['video_sha256']='b'*64
  with self.assertRaisesRegex(ValueError,'bytes changed'):self.submit()
  self.assertFalse(self.p.calls)
 def test_under_ten_minutes_never_uploads(self):
  self.details['duration_seconds']=599
  with self.assertRaisesRegex(ValueError,'insufficient'):self.submit()
  self.assertFalse(self.p.calls)
 def test_duplicate_sources_blocked(self):
  self.plan*=2
  with self.assertRaisesRegex(ValueError,'duplicate'):self.submit()
 def test_confirmed_publication_is_required(self):
  self.submit();self.assertNotIn('published_at',list(self.s['compilation_attempts'].values())[0])
  self.p.status='PUBLISHED';self.d.reconcile()
  self.assertEqual(list(self.s['compilation_attempts'].values())[0]['state'],'published')
  self.assertEqual(self.submit(),'cadence_wait')
 def test_destination_readback_mismatch_keeps_pending(self):
  self.p.post=lambda *a:{'id':'post-id','projectId':'other'}
  with self.assertRaisesRegex(ValueError,'identity'):self.submit()
  self.assertEqual(list(self.s['compilation_attempts'].values())[0]['state'],'delivery_recorded')
 def test_nonrepeated_plan_and_no_looping(self):
  self.assertEqual(choose_plan([{'duration_seconds':599}]),[])
  self.assertEqual(len(choose_plan([{'duration_seconds':1000}])),1)
  self.assertEqual(len(choose_plan([{'duration_seconds':310},{'duration_seconds':300}])),2)
 def test_next_batch_excludes_already_compiled_sources_and_bytes(self):
  s={'compilation_attempts':{'previous':{'state':'published','source_keys':['1:1'],'source_sha256':['old']}}}
  rows=[{'key':'1:2','sha256':'new'},{'key':'2:1','sha256':'old'},{'key':'3:1','sha256':'fresh'}]
  self.assertEqual(unused_rows(s,rows),[rows[2]])
 def test_source_text_not_invented_in_title(self):
  title,description,anchor=metadata([{'post_id':'123','text':'اختبار الحدث https://example.com @test'}])
  self.assertEqual(anchor,'اختبار الحدث');self.assertIn('/status/123',description);self.assertNotIn('@test',title)
 def test_real_synthetic_media_render(self):
  import subprocess
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);src=base/'source.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:r=25','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3.2','-c:v','libx264','-threads','2','-c:a','aac',str(src)],check=True)
   data=src.read_bytes();digest=sha(data)
   from compilation_assessment import probe_bytes
   dur=probe_bytes(data)
   s={'state':{'pending':[{'post_id':'1','media_id':'1','video_url':'fake','text':'تجربة'}]},'prepared_media':{'1:1':{'sha256':digest}},'audio_reviews':{'1:1':{'synthetic':True}}}
   plan=[{'key':'1:1','sha256':digest,'duration_seconds':dur}]
   # Reduced duration only in this isolated media integration test. Production is 600 seconds.
   with patch('compilation_delivery.MIN',3):
    details=render(s,plan,lambda *a:True,base/'out.mp4',base/'thumb.jpg',fetch=lambda url:data)
   self.assertGreaterEqual(details['duration_seconds'],3)
   from PIL import Image
   with Image.open(base/'thumb.jpg') as image:self.assertEqual(image.size,(1280,720))
 def test_changed_source_cannot_render(self):
  s={'state':{'pending':[{'post_id':'1','media_id':'1','video_url':'url'}]},'prepared_media':{},'audio_reviews':{}}
  with tempfile.TemporaryDirectory() as d,self.assertRaisesRegex(ValueError,'source changed'):
   render(s,self.plan,lambda *a:True,Path(d)/'v',Path(d)/'t',fetch=lambda url:b'bad')

if __name__=='__main__':unittest.main()
