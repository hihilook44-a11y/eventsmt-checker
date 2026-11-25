"""Synthetic checks: prevent repeated Shorts across the two queue stages and runs."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from workflow_pipeline import short_cadence_wait, publish_reviewed
from candidate_pipeline import PipelineError

class CadenceTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,25,21,0,tzinfo=timezone.utc)
    def snap(self, state='delivery_scheduled', at=None):
        return {'candidate_deliveries':{'1:2':{'state':state,'scheduled_for':at or self.now.isoformat()}}}
    def test_blocks_two_stages_and_independent_runs_until_one_hour(self):
        for state in ('delivery_scheduled','delivery_recorded','delivery_uncertain','published'):
            s=self.snap(state)
            self.assertTrue(short_cadence_wait(s,self.now+timedelta(minutes=1)))
            self.assertTrue(short_cadence_wait(s,self.now+timedelta(minutes=59,seconds=59)))
            self.assertFalse(short_cadence_wait(s,self.now+timedelta(hours=1)))
    def test_future_scheduled_short_blocks_and_failed_does_not(self):
        self.assertTrue(short_cadence_wait(self.snap(at=(self.now+timedelta(minutes=5)).isoformat()),self.now))
        self.assertFalse(short_cadence_wait(self.snap('delivery_failed'),self.now))
    def test_invalid_timestamp_fails_closed_and_old_legacy_does_not_block(self):
        for invalid in ('garbage','2026-11-25T21:00:00'):
            with self.assertRaises(PipelineError):short_cadence_wait(self.snap(at=invalid),self.now)
        self.assertFalse(short_cadence_wait({'candidate_deliveries':{'1:2':{'state':'published'}}},self.now))
    def test_direct_publication_returns_before_audio_upload_or_remote_write(self):
        s=self.snap(at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        with patch('workflow_pipeline.CandidatePipeline') as pipeline:
            self.assertEqual(publish_reviewed(s,lambda s:None,object(),{},b'',None,None,None,None),'cadence_wait')
            pipeline.assert_not_called()
    def test_real_workflow_runs_pipeline_before_and_after_assessment(self):
        from pathlib import Path
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/private-queue.yml').read_text()
        self.assertEqual(workflow.count('run: python private_queue/workflow_pipeline.py'),2)
        self.assertIn('scripts/queue_lease.py acquire',workflow)

if __name__=='__main__':unittest.main()
