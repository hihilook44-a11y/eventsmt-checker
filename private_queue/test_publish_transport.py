import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from woopsocial_adapter import Provider,ProviderError
class TransportTests(unittest.TestCase):
 def test_youtube_publish_payload_and_result(self):
  p=Provider(key='test'); calls=[]
  def call(method,path,body,ctype):
   calls.append((method,path,json.loads(body),ctype));return {'id':'post','schedule':{'type':'PUBLISH_NOW'}}
  p.call=call
  self.assertEqual(p.publish_now('account','title','desc','media'),'post')
  method,path,payload,ctype=calls[0]
  self.assertEqual((method,path,ctype),('POST','/posts','application/json'))
  self.assertEqual(payload['schedule'],{'type':'PUBLISH_NOW'})
  self.assertEqual(payload['socialAccounts'],[{'platform':'YOUTUBE','socialAccountId':'account','title':'title','privacy':'public'}])
  self.assertEqual(payload['content'][0]['media'][0]['mediaId'],'media')
 def test_invalid_response_is_uncertain(self):
  p=Provider(key='test');p.call=lambda *a:{'schedule':{'type':'DRAFT'},'id':'p'}
  with self.assertRaises(ProviderError):p.publish_now('a','title','desc','m')
if __name__=='__main__':unittest.main()
