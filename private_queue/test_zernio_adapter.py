import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from zernio_adapter import ZernioProvider, ZernioError, stable_idempotency_key

PROFILE='6af2cbbf52dc01c8f7628d74'
ACCOUNT='6af2cbec3844166cbc3e7971'

class ZernioAdapterTests(unittest.TestCase):
    def setUp(self):
        self.p=ZernioProvider(key='test-secret',profile=PROFILE,account=ACCOUNT)
        self.calls=[]

    def test_destination_is_exact_profile_youtube_account(self):
        self.p._api=lambda method,path,payload=None,headers=None:{'accounts':[{'_id':ACCOUNT,'platform':'youtube','status':'connected','enabled':True}]}
        self.assertTrue(self.p.verify_destination(PROFILE,ACCOUNT))
        self.assertFalse(self.p.verify_destination('a'*24,ACCOUNT))
        self.p._api=lambda *a,**k:{'accounts':[{'_id':ACCOUNT,'platform':'youtube','status':'disconnected'}]}
        self.assertFalse(self.p.verify_destination(PROFILE,ACCOUNT))

    def test_schedule_payload_is_idempotent_public_youtube(self):
        def api(method,path,payload=None,headers=None):
            self.calls.append((method,path,payload,headers))
            return {'post':{'_id':'post-1','status':'scheduled','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'pending'}]}}
        self.p._api=api
        idem=stable_idempotency_key(ACCOUNT,'123:456','a'*64)
        self.assertEqual(self.p.publish_scheduled(ACCOUNT,'title','description','https://media.zernio.com/temp/v.mp4','2026-11-10T11:00:00Z',idem),'post-1')
        method,path,body,headers=self.calls[0]
        self.assertEqual((method,path),('POST','/posts'))
        self.assertEqual(headers,{'Idempotency-Key':idem})
        self.assertEqual(body['platforms'][0]['platformSpecificData'],{'title':'title','visibility':'public'})
        self.assertEqual(body['platforms'][0]['scheduledFor'],'2026-11-10T11:00:00Z')
        self.assertEqual(body['metadata']['eventsmtPipelineKey'],idem)
        self.assertNotIn('publishNow',body)

    def test_non_scheduled_create_is_not_reported_as_confirmed(self):
        self.p._api=lambda *a,**k:{'post':{'_id':'post-1','status':'published','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'published'}]}}
        with self.assertRaises(ZernioError):
            self.p.publish_scheduled(ACCOUNT,'title','description','https://media.zernio.com/temp/v.mp4','2026-11-10T11:00:00Z','key')

    def test_post_normalizes_scheduled_and_published_for_pipeline(self):
        self.p._api=lambda *a,**k:{'post':{'_id':'p','status':'scheduled','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'pending'}]}}
        post=self.p.post('p')
        self.assertEqual(post['id'],'p')
        self.assertEqual(post['projectId'],PROFILE)
        self.assertEqual(post['socialAccountPosts'][0]['deliveryStatus'],'SCHEDULED')
        self.p._api=lambda *a,**k:{'post':{'_id':'p','status':'published','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'published','platformPostUrl':'https://youtube.com/watch?v=x'}]}}
        post=self.p.post('p')
        self.assertEqual(post['socialAccountPosts'][0]['deliveryStatus'],'PUBLISHED')

if __name__=='__main__': unittest.main()
