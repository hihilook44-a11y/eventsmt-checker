import json
import io
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
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

    def test_api_error_reports_fixed_endpoint_without_query(self):
        def fail(*args, **kwargs):
            raise ZernioError('HTTP 403')
        self.p._request=fail
        with self.assertRaisesRegex(ZernioError, 'GET accounts: HTTP 403') as caught:
            self.p._api('GET','/accounts?profileId=private-profile')
        self.assertNotIn('private-profile',str(caught.exception))

    def test_http_error_logs_only_allowlisted_type(self):
        class BadOpener:
            def open(self, req, timeout):
                body=b'{"type":"invalid_request_error","error":"private-post-id and secret"}'
                raise HTTPError(req.full_url, 400, 'Bad Request', {}, io.BytesIO(body))
        self.p.opener=BadOpener()
        with self.assertRaisesRegex(ZernioError, 'GET posts: HTTP 400 invalid_request_error') as caught:
            self.p._api('GET','/posts/opaque-post-id')
        self.assertNotIn('private-post-id',str(caught.exception))
        self.assertNotIn('secret',str(caught.exception))
        self.assertNotIn('opaque-post-id',str(caught.exception))

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

    def test_post_create_accepts_documented_207_partial_response(self):
        class Response:
            status=207
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return b'{"post":{"_id":"post-1","status":"partial"}}'
        class Opener:
            def open(self,req,timeout): return Response()
        self.p.opener=Opener()
        result=self.p._api('POST','/posts',{'content':'caption'})
        self.assertEqual(result['post']['status'],'partial')

    def test_scheduled_destination_status_is_accepted_case_insensitively(self):
        for status in ('scheduled', 'SCHEDULED'):
            with self.subTest(status=status):
                self.p._api=lambda *a, _status=status, **k:{'post':{'_id':'post-1','status':'scheduled','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':_status}]}}
                idem=stable_idempotency_key(ACCOUNT,'123:456','a'*64)
                self.assertEqual(self.p.publish_scheduled(ACCOUNT,'title','description','https://media.zernio.com/temp/v.mp4','2026-11-10T11:00:00Z',idem),'post-1')

    def test_published_create_response_is_read_back_not_rejected(self):
        self.p._api=lambda *a,**k:{'post':{'_id':'post-1','status':'published','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'published'}]}}
        self.assertEqual(self.p.publish_scheduled(ACCOUNT,'title','description','https://media.zernio.com/temp/v.mp4','2026-11-10T11:00:00Z','key'),'post-1')

    def test_create_response_id_is_checkpointable_without_platform_rows(self):
        self.p._api=lambda *a,**k:{'post':{'_id':'post-1','status':'scheduled'}}
        self.assertEqual(self.p.publish_scheduled(ACCOUNT,'title','description','https://media.zernio.com/temp/v.mp4','2026-11-10T11:00:00Z','key'),'post-1')

    def test_unknown_overall_status_is_rejected(self):
        media='https://media.zernio.com/temp/v.mp4'
        self.p._api=lambda *a,**k:{'post':{'_id':'post-1','status':'queued','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'pending'}]}}
        with self.assertRaises(ZernioError): self.p.publish_scheduled(ACCOUNT,'title','description',media,'2026-11-10T11:00:00Z','key')

    def test_post_normalizes_scheduled_and_published_for_pipeline(self):
        self.p._api=lambda *a,**k:{'post':{'_id':'p','status':'scheduled','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'pending'}]}}
        post=self.p.post('p')
        self.assertEqual(post['id'],'p')
        self.assertEqual(post['projectId'],PROFILE)
        self.assertEqual(post['socialAccountPosts'][0]['deliveryStatus'],'SCHEDULED')
        self.assertEqual(post['socialAccountPosts'][0]['platform'],'youtube')
        self.p._api=lambda *a,**k:{'post':{'_id':'p','status':'published','platforms':[{'platform':'youtube','accountId':ACCOUNT,'status':'published','platformPostUrl':'https://youtube.com/watch?v=x'}]}}
        post=self.p.post('p')
        self.assertEqual(post['socialAccountPosts'][0]['deliveryStatus'],'PUBLISHED')

if __name__=='__main__': unittest.main()
