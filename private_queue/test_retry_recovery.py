import copy, hashlib, sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import workflow_pipeline as wp
from candidate_pipeline import CandidatePipeline, PipelineError
from zernio_adapter import stable_idempotency_key

KEY='123:456'; ACCOUNT='account'; PROFILE='profile'; DATA=b'exact previously reviewed bytes'
DIGEST=hashlib.sha256(DATA).hexdigest(); NOW=datetime(2026,11,10,17,45,tzinfo=timezone.utc)
class Provider:
    name='zernio'; profile=PROFILE; account=ACCOUNT
    def __init__(self): self.posts=[]
    def verify_destination(self,project,account): return project==PROFILE and account==ACCOUNT
    def verify_media(self,project,media): return project==PROFILE and media=='https://media.zernio.com/a.mp4'
    def publish_scheduled(self,*args): self.posts.append(args); return 'abc123abc123abc123abc123'

def snapshot():
    scheduled=(NOW+timedelta(minutes=10)).isoformat().replace('+00:00','Z')
    idem=stable_idempotency_key(ACCOUNT,KEY,DIGEST)
    item={'post_id':'123','media_id':'456','video_url':'https://cdn.example/a.mp4','text':'A reviewed clip https://x.com/post'}
    record={'state':'delivery_uncertain','provider':'zernio','project':PROFILE,'account':ACCOUNT,
            'media_id':'https://media.zernio.com/a.mp4','scheduled_for':scheduled,
            'idempotency_key':idem,'sha256':DIGEST}
    return {'state':{'pending':[item]},'ledger':{'published_source_ids':[]},
            'candidate_deliveries':{KEY:record},'audio_reviews':{KEY:{'ok':True}}}

class CandidateRetryTests(unittest.TestCase):
    def test_only_exact_uncertain_attempt_can_retry(self):
        s=snapshot(); p=Provider(); saved=[]
        pipeline=CandidatePipeline(s,lambda state:saved.append(copy.deepcopy(state)),p)
        r=s['candidate_deliveries'][KEY]
        got=pipeline.retry_scheduled_idempotently(KEY,ACCOUNT,'title','desc',r['scheduled_for'],r['idempotency_key'])
        self.assertEqual(got,'abc123abc123abc123abc123')
        self.assertEqual(len(p.posts),1)
        self.assertEqual(saved[0]['candidate_deliveries'][KEY]['state'],'delivery_recorded')
        self.assertEqual(s['candidate_deliveries'][KEY]['state'],'delivery_recorded')
        self.assertEqual(s['candidate_deliveries'][KEY]['post_id'],got)

    def test_mismatched_retry_parameters_do_not_call_provider(self):
        for field,value in [('account','other'),('idempotency_key','wrong'),('scheduled_for','wrong')]:
            s=snapshot();p=Provider();r=s['candidate_deliveries'][KEY];r[field]=value
            pipeline=CandidatePipeline(s,lambda state:None,p)
            with self.assertRaises(PipelineError):
                pipeline.retry_scheduled_idempotently(KEY,ACCOUNT,'title','desc',snapshot()['candidate_deliveries'][KEY]['scheduled_for'],snapshot()['candidate_deliveries'][KEY]['idempotency_key'])
            self.assertEqual(p.posts,[])

class RecoveryGateTests(unittest.TestCase):
    def run_recovery(self,s,p,now=NOW,valid=True):
        saved=[]
        def verify(item,data,proof): return valid and item['post_id']=='123' and data==DATA and proof=={'ok':True}
        with patch.dict('os.environ',{'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'true'}), patch.object(wp,'get_media',return_value=DATA):
            result=wp.recover_uncertain_scheduled(s,lambda state:saved.append(copy.deepcopy(state)),p,verify,now)
        return result,saved

    def test_verified_recent_attempt_recovers_with_original_key(self):
        s=snapshot();p=Provider();result,saved=self.run_recovery(s,p)
        self.assertTrue(result);self.assertEqual(len(p.posts),1);self.assertEqual(len(saved),1)
        self.assertEqual(s['candidate_deliveries'][KEY]['state'],'delivery_recorded')
        self.assertEqual(p.posts[0][-1],snapshot()['candidate_deliveries'][KEY]['idempotency_key'])

    def test_expired_attempt_unreviewed_bytes_or_wrong_destination_are_not_retried(self):
        s=snapshot();p=Provider();result,_=self.run_recovery(s,p,NOW+timedelta(hours=23))
        self.assertFalse(result);self.assertEqual(len(p.posts),0)
        s=snapshot();p=Provider();result,_=self.run_recovery(s,p,NOW+timedelta(hours=22,minutes=10))
        self.assertFalse(result);self.assertEqual(len(p.posts),0)
        s=snapshot();p=Provider();result,_=self.run_recovery(s,p,valid=False)
        self.assertFalse(result);self.assertEqual(len(p.posts),0)
        s=snapshot();p=Provider();s['candidate_deliveries'][KEY]['account']='wrong'
        result,_=self.run_recovery(s,p)
        self.assertFalse(result);self.assertEqual(len(p.posts),0)

    def test_disabled_provider_does_not_retry(self):
        s=snapshot();p=Provider()
        with patch.dict('os.environ',{'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'false'}):
            self.assertFalse(wp.recover_uncertain_scheduled(s,lambda state:None,p,lambda *_:True,NOW))
        self.assertEqual(len(p.posts),0)

if __name__=='__main__': unittest.main()
