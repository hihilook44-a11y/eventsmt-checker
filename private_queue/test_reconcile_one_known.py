import copy
import hashlib
import unittest
from unittest.mock import patch
import reconcile_one_known as r
from zernio_adapter import stable_idempotency_key

class P:
    profile='p'; account='a'

class Match(unittest.TestCase):
    def setUp(self):
        self.key=r.SOURCE_ID+':123'
        digest=hashlib.sha256(b'video').hexdigest()
        rec={'state':'delivery_uncertain','provider':'zernio','project':'p','account':'a',
             'media_id':'https://media.zernio.com/uploaded/test.mp4','sha256':digest}
        rec['idempotency_key']=stable_idempotency_key('a',self.key,rec['sha256'])
        item={'post_id':r.SOURCE_ID,'media_id':'123','video_url':'https://video.twimg.com/source.mp4'}
        self.s={'candidate_deliveries':{self.key:rec},'state':{'pending':[item]},'audio_reviews':{self.key:{'signed':'proof'}}}
        self.raw={'post':{'_id':r.POST_ID,'content':'hello https://x.com/__eventsMT/status/'+r.SOURCE_ID,
             'metadata':{'eventsmtPipelineKey':rec['idempotency_key']},
             'mediaItems':[{'url':'https://media.zernio.com/posts/different-path.mp4'}],
             'platforms':[{'accountId':'a','platform':'youtube','status':'published','platformPostId':'video'}]}}

    def test_match_accepts_provider_regenerated_url_when_review_hash_matches(self):
        with patch.object(r,'media_sha256',return_value=self.s['candidate_deliveries'][self.key]['sha256']) as digest, \
             patch.object(r,'get_media',return_value=b'video'), \
             patch.object(r,'youtube_video_verified',return_value=True):
            verify=lambda item,data,proof: proof=={'signed':'proof'} and data==b'video'
            self.assertEqual(r.match_record(self.s,P(),self.raw,verify)[0],self.key)
        self.assertEqual(digest.call_count,2)

    def test_identical_urls_are_hashed_once(self):
        self.raw['post']['mediaItems'][0]['url']=self.s['candidate_deliveries'][self.key]['media_id']
        with patch.object(r,'media_sha256',return_value=self.s['candidate_deliveries'][self.key]['sha256']) as digest, \
             patch.object(r,'get_media',return_value=b'video'), \
             patch.object(r,'youtube_video_verified',return_value=True):
            r.match_record(self.s,P(),self.raw,lambda *args:True)
        digest.assert_called_once()

    def test_bad_evidence_rejected(self):
        for field,value in [('content','other'),('_id','other'),('metadata',{}),('mediaItems',[])]:
            bad=copy.deepcopy(self.raw); bad['post'][field]=value
            with patch.object(r,'media_sha256',return_value=self.s['candidate_deliveries'][self.key]['sha256']), \
                 patch.object(r,'get_media',return_value=b'video'), \
                 patch.object(r,'youtube_video_verified',return_value=True):
                with self.assertRaises(ValueError): r.match_record(self.s,P(),bad,lambda *args:True)

    def test_mismatched_record_rejected(self):
        for field,value in [('provider','other'),('state','published'),('post_id','already'),('project','other'),('account','other'),('media_id','other'),('idempotency_key','other')]:
            state=copy.deepcopy(self.s); state['candidate_deliveries'][self.key][field]=value
            with patch.object(r,'media_sha256',side_effect=lambda url: None if url=='other' else state['candidate_deliveries'][self.key]['sha256']), \
                 patch.object(r,'get_media',return_value=b'video'), \
                 patch.object(r,'youtube_video_verified',return_value=True):
                with self.assertRaises(ValueError): r.match_record(state,P(),self.raw,lambda *args:True)

    def test_media_hash_disagreement_rejected(self):
        with patch.object(r,'media_sha256',side_effect=['a'*64,'b'*64]):
            with self.assertRaisesRegex(ValueError,'media fingerprint mismatch'):
                r.match_record(self.s,P(),self.raw,lambda *args:True)

    def test_missing_or_invalid_review_hash_rejected(self):
        record=self.s['candidate_deliveries'][self.key]
        record['sha256']='abc'
        record['idempotency_key']=stable_idempotency_key('a',self.key,'abc')
        self.raw['post']['metadata']['eventsmtPipelineKey']=record['idempotency_key']
        with self.assertRaisesRegex(ValueError,'review fingerprint missing'):
            r.match_record(self.s,P(),self.raw,lambda *args:True)

    def test_requires_signed_audio_clearance_and_public_channel(self):
        with patch.object(r,'media_sha256',return_value=self.s['candidate_deliveries'][self.key]['sha256']), \
             patch.object(r,'get_media',return_value=b'video'), \
             patch.object(r,'youtube_video_verified',return_value=True):
            with self.assertRaisesRegex(ValueError,'signed no-songs review'):
                r.match_record(self.s,P(),self.raw,lambda *args:False)
        with patch.object(r,'media_sha256',return_value=self.s['candidate_deliveries'][self.key]['sha256']), \
             patch.object(r,'get_media',return_value=b'video'), \
             patch.object(r,'youtube_video_verified',return_value=False):
            with self.assertRaisesRegex(ValueError,'public YouTube video/channel'):
                r.match_record(self.s,P(),self.raw,lambda *args:True)

    def test_untrusted_hosts_not_downloaded(self):
        with patch.object(r.urllib.request,'urlopen') as urlopen:
            self.assertIsNone(r.media_sha256('https://example.com/anything'))
        urlopen.assert_not_called()

if __name__=='__main__': unittest.main()
