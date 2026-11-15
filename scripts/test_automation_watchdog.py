import sys,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parent))
from automation_watchdog import decide,queue_parent_covers
class WatchdogTests(unittest.TestCase):
 def setUp(self):self.now=datetime(2026,11,11,16,30,tzinfo=timezone.utc)
 def run_at(self,delta,status='completed'):
  return {'createdAt':(self.now-timedelta(seconds=delta)).isoformat(),'status':status}
 def test_missing_is_due(self):self.assertEqual(decide([],None,self.now,7200),'due')
 def test_recent_run_suppresses_duplicate(self):self.assertEqual(decide([self.run_at(100)],None,self.now,7200),'recent_run')
 def test_old_is_due(self):self.assertEqual(decide([self.run_at(7201)],None,self.now,7200),'due')
 def test_any_active_suppresses_duplicate(self):self.assertEqual(decide([self.run_at(9000,'queued')],None,self.now,7200),'active_run')
 def test_unknown_never_blindly_retries(self):
  for age,expected in [(100,'awaiting_dispatch_readback'),(8000,'unresolved_dispatch')]:
   receipt={'state':'unknown','attempted_at':(self.now-timedelta(seconds=age)).isoformat()}
   self.assertEqual(decide([],receipt,self.now,7200),expected)
 def test_remote_run_resolves_local_receipt(self):
  receipt={'state':'unknown','attempted_at':(self.now-timedelta(seconds=100)).isoformat()}
  self.assertEqual(decide([self.run_at(95)],receipt,self.now,7200),'recent_run')
 def test_future_does_not_trigger(self):self.assertEqual(decide([self.run_at(-30)],None,self.now,7200),'recent_run')
 def test_invalid_response_stops(self):
  for value in [{},[None],[{'createdAt':'broken'}]]:
   with self.assertRaises((ValueError,KeyError)):decide(value,None,self.now,7200)

 def test_recent_parent_with_successful_reusable_queue_suppresses_dispatch(self):
  parent={'databaseId':42,'createdAt':(self.now-timedelta(minutes=5)).isoformat(),'status':'completed'}
  jobs={'42':[{'name':'backup-private-queue / scan','status':'completed','conclusion':'success'}]}
  self.assertTrue(queue_parent_covers([parent],jobs,self.now,7200))
 def test_active_parent_suppresses_duplicate_queue_dispatch_even_if_long_running(self):
  parent={'databaseId':42,'createdAt':(self.now-timedelta(hours=3)).isoformat(),'status':'in_progress'}
  self.assertTrue(queue_parent_covers([parent],{},self.now,7200))
 def test_failed_or_missing_reusable_queue_does_not_suppress_recovery(self):
  parent={'databaseId':42,'createdAt':(self.now-timedelta(minutes=5)).isoformat(),'status':'completed'}
  jobs={'42':[{'name':'backup-private-queue / scan','status':'completed','conclusion':'failure'}]}
  self.assertFalse(queue_parent_covers([parent],jobs,self.now,7200))
  self.assertFalse(queue_parent_covers([parent],{},self.now,7200))
 def test_old_parent_does_not_suppress_recovery(self):
  parent={'databaseId':42,'createdAt':(self.now-timedelta(hours=3)).isoformat(),'status':'completed'}
  jobs={'42':[{'name':'backup-private-queue / scan','status':'completed','conclusion':'success'}]}
  self.assertFalse(queue_parent_covers([parent],jobs,self.now,7200))

if __name__=='__main__':unittest.main()
