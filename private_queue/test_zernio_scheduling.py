import copy, hashlib, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_pipeline import CandidatePipeline, PipelineError
from workflow_pipeline import delivery_in_flight, zernio_scheduling_enabled, publish_reviewed

KEY='12:34'; DATA=b'checked bytes'; DIGEST=hashlib.sha256(DATA).hexdigest()
class Provider:
    name='zernio'
    def __init__(self): self.posts=0; self.s=None
    def verify_media(self,profile,url): return profile=='profile' and url=='https://media.zernio.com/v.mp4'
    def publish_scheduled(self,*args):
        self.posts+=1
        assert self.s['candidate_deliveries'][KEY]['state']=='delivery_uncertain'
        return 'scheduled-id'

class ZernioSchedulingTests(unittest.TestCase):
    def test_zernio_is_disabled_without_explicit_flag_even_if_key_exists(self):
        self.assertFalse(zernio_scheduling_enabled({}))
        self.assertFalse(zernio_scheduling_enabled({'ZERNIO_API_KEY':'present'}))
        self.assertTrue(zernio_scheduling_enabled({'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'true'}))
        self.assertFalse(zernio_scheduling_enabled({'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'false'}))

    def test_publish_entrypoint_fails_closed_when_disabled(self):
        from unittest.mock import patch
        item={'post_id':'12','media_id':'34','text':'title'}
        with patch.dict('os.environ', {'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'false'}):
            with self.assertRaisesRegex(PipelineError,'disabled'):
                publish_reviewed(self.s,self.checkpoint,self.p,item,DATA,None,lambda *_:True,'profile','account')
        self.assertEqual(self.p.posts,0)

    def setUp(self):
        self.s={'state':{'pending':[{'post_id':'12','media_id':'34'}]},'ledger':{'published_source_ids':[]},
                'candidate_deliveries':{KEY:{'sha256':DIGEST,'state':'upload_complete','project':'profile','media_id':'https://media.zernio.com/v.mp4'}}}
        self.saved=copy.deepcopy(self.s); self.p=Provider();self.p.s=self.s
    def checkpoint(self,s): self.saved=copy.deepcopy(s)
    def test_checkpoint_before_create_and_recorded_result(self):
        cp=CandidatePipeline(self.s,self.checkpoint,self.p)
        self.assertEqual(cp.publish_scheduled(KEY,'account','title','description','time','idempotency'),'scheduled-id')
        self.assertEqual(self.p.posts,1)
        self.assertEqual(self.saved['candidate_deliveries'][KEY]['state'],'delivery_recorded')
        self.assertEqual(self.saved['candidate_deliveries'][KEY]['provider'],'zernio')
        self.assertTrue(delivery_in_flight(self.saved))
    def test_known_scheduled_state_does_not_block_other_work(self):
        self.s['candidate_deliveries'][KEY].update(state='delivery_scheduled',post_id='scheduled-id')
        self.assertFalse(delivery_in_flight(self.s))
    def test_new_shorts_default_to_five_minute_schedule(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        item={'post_id':'12','media_id':'34','text':'title'}
        with patch.dict('os.environ', {'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'true'}, clear=True), \
             patch('workflow_pipeline.exact_destination', return_value=True), \
             patch('workflow_pipeline.CandidatePipeline.publish_scheduled') as create, \
             patch('workflow_pipeline.reconcile_known_deliveries'):
            before=datetime.now(timezone.utc)
            publish_reviewed(self.s,self.checkpoint,self.p,item,DATA,True,lambda *_:True,'profile','account')
            after=datetime.now(timezone.utc)
        scheduled=datetime.fromisoformat(create.call_args.args[4].replace('Z','+00:00'))
        self.assertGreaterEqual((scheduled-before).total_seconds(), 299)
        self.assertLessEqual((scheduled-after).total_seconds(), 300)
        self.assertIn('#fivem #Mtfivem', create.call_args.args[3])

    def test_below_safe_delay_never_creates_post(self):
        from unittest.mock import patch
        item={'post_id':'12','media_id':'34','text':'title'}
        with patch.dict('os.environ', {'ZERNIO_SCHEDULED_PUBLISHING_ENABLED':'true','ZERNIO_SCHEDULE_DELAY_MINUTES':'4'}), \
             patch('workflow_pipeline.exact_destination',return_value=True), \
             patch('workflow_pipeline.CandidatePipeline.publish_scheduled') as create:
            with self.assertRaisesRegex(PipelineError,'outside safe range'):
                publish_reviewed(self.s,self.checkpoint,self.p,item,DATA,True,lambda *_:True,'profile','account')
        create.assert_not_called()

    def test_wrong_media_fails_without_create(self):
        self.s['candidate_deliveries'][KEY]['media_id']='https://media.zernio.com/other.mp4'
        cp=CandidatePipeline(self.s,self.checkpoint,self.p)
        with self.assertRaises(PipelineError): cp.publish_scheduled(KEY,'account','title','desc','time','idempotency')
        self.assertEqual(self.p.posts,0)

if __name__=='__main__': unittest.main()
