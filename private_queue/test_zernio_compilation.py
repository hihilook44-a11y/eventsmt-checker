import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from zernio_adapter import ZernioProvider,ZernioError
class Tests(unittest.TestCase):
 def setUp(self):
  self.p=ZernioProvider(key='test',profile='a'*24,account='b'*24)
  self.calls=[]
 def test_compilation_payload_has_custom_thumbnail(self):
  def api(*args):
   self.calls.append(args);return {'post':{'_id':'p','status':'scheduled'}}
  self.p._api=api
  self.assertEqual(self.p.publish_compilation('b'*24,'title','description','https://media.zernio.com/v.mp4','https://media.zernio.com/t.jpg','2026-11-12T00:00:00Z','idem'),'p')
  payload=self.calls[0][2]
  self.assertEqual(payload['mediaItems'][0]['thumbnail'],'https://media.zernio.com/t.jpg')
  self.assertEqual(payload['platforms'][0]['platformSpecificData']['visibility'],'public')
  self.assertEqual(self.calls[0][3],{'Idempotency-Key':'idem'})
 def test_unknown_response_stays_uncertain(self):
  self.p._api=lambda *args:{'post':{'status':'scheduled'}}
  with self.assertRaises(ZernioError):self.p.publish_compilation('b'*24,'t','d','https://media.zernio.com/v.mp4','https://media.zernio.com/t.jpg','time','idem')
 def test_wrong_thumbnail_host_blocks_before_post(self):
  self.p._api=lambda *a:self.fail('must not send')
  with self.assertRaises(ValueError):self.p.publish_compilation('b'*24,'t','d','https://media.zernio.com/v.mp4','https://example.com/t.jpg','time','idem')
 def test_thumbnail_put_is_unauthenticated(self):
  self.p._api=lambda *a:{'uploadUrl':'https://upload.example/path','publicUrl':'https://media.zernio.com/t.jpg'}
  self.p._request=lambda *args,**kwargs:self.calls.append((args,kwargs))
  self.assertEqual(self.p.upload_image('a'*24,b'image'),'https://media.zernio.com/t.jpg')
  self.assertFalse(self.calls[0][1]['authorized'])
  self.assertEqual(self.calls[0][0][0],'PUT')
 def test_thumbnail_oversize_rejected_before_network(self):
  self.p._api=lambda *a:self.fail('must not send')
  with self.assertRaises(ValueError):self.p.upload_image('a'*24,b'x'*2000001)
if __name__=='__main__':unittest.main()
