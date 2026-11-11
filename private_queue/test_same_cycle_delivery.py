"""A passing assessment needs no second scheduled cycle; gates remain intact."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from workflow_pipeline import register_and_deliver

class SameCycleTests(unittest.TestCase):
    def setUp(self):
        self.item={'post_id':'12','media_id':'34','created_at':datetime.now(timezone.utc).isoformat()}
        self.s={}; self.proof={'synthetic': True}
    def run_case(self, verifier, project='project', account='account'):
        return register_and_deliver(self.s,lambda s:None,object(),self.item,b'synthetic',verifier,project,account)
    @patch('workflow_pipeline.publish_reviewed',return_value='delivery_scheduled')
    @patch('workflow_pipeline.audio_proofs',return_value={'12:34':{'synthetic':True}})
    @patch('workflow_pipeline.run_candidate',return_value='awaiting_audio_review')
    def test_pass_delivers_same_cycle(self,register,proofs,publish):
        self.assertEqual(self.run_case(lambda *args:True),'delivery_scheduled')
        register.assert_called_once();publish.assert_called_once()
    @patch('workflow_pipeline.publish_reviewed')
    @patch('workflow_pipeline.audio_proofs',return_value={})
    @patch('workflow_pipeline.run_candidate',return_value='awaiting_audio_review')
    def test_suspected_or_missing_proof_remains_blocked(self,register,proofs,publish):
        self.assertEqual(self.run_case(lambda *args:False),'awaiting_audio_review')
        publish.assert_not_called()
    @patch('workflow_pipeline.publish_reviewed')
    @patch('workflow_pipeline.audio_proofs',return_value={'12:34':{'synthetic':True}})
    @patch('workflow_pipeline.run_candidate',return_value='awaiting_audio_review')
    def test_stale_or_missing_destination_never_delivers(self,register,proofs,publish):
        self.run_case(lambda *args:True,account='')
        self.item['created_at']=(datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        self.run_case(lambda *args:True)
        publish.assert_not_called()
    @patch('workflow_pipeline.publish_reviewed')
    @patch('workflow_pipeline.run_candidate',side_effect=RuntimeError('checkpoint failed'))
    def test_registration_failure_never_submits(self,register,publish):
        with self.assertRaises(RuntimeError): self.run_case(lambda *args:True)
        publish.assert_not_called()

if __name__=='__main__':unittest.main()
