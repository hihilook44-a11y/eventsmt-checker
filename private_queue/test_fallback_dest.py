import unittest
from unittest.mock import patch
from workflow_pipeline import established_destination
import paginated_candidates
class P:
 def __init__(self,name='Mt Fivem- زيكو',status='CONNECTED',pid='p',aid='a'):
  self.name=name;self.status=status;self.pid=pid;self.aid=aid
 def projects(self):return [{'id':self.pid}]
 def call(self,*args):return [{'id':self.aid,'username':self.name,'status':self.status,'platform':'YOUTUBE'}]
def snapshot(state='verified_draft'):return {'integration_test':{'state':state,'project':'p','account':'a'}}
class T(unittest.TestCase):
 def test_exact_previously_verified_target(self):self.assertEqual(established_destination(snapshot(),P()),('p','a'))
 def test_wrong_or_unverified_target_is_refused(self):
  for snap,provider in [(snapshot('uploaded'),P()),(snapshot(),P(name='other')),(snapshot(),P(status='DISCONNECTED')),(snapshot(),P(aid='other')),(snapshot(),P(pid='other'))]:self.assertEqual(established_destination(snap,provider),(None,None))
 def test_statuses_endpoint_validated(self):
  with patch.object(paginated_candidates,'LEDGER') as ledger:
   ledger.read_text.return_value='{"published_source_ids": []}'
   with patch.object(paginated_candidates.urllib.request,'urlopen',side_effect=RuntimeError('stop')) as f:
    result=paginated_candidates.run(1,100,'statuses');self.assertTrue(result['errors']);self.assertIn('/statuses?',f.call_args.args[0].full_url)
  with self.assertRaises(ValueError):paginated_candidates.run(endpoint='other')
if __name__=='__main__':unittest.main()

class FallbackScan(unittest.TestCase):
 def test_media_failure_then_statuses_validates_before_update(self):
  import json, tempfile, sys
  from pathlib import Path
  import scheduled_private_scan as m
  failed={'errors':['Page 1: HTTPError: HTTP Error 404: X'],'pages':[]}
  ok={'errors':[],'pages':[{'timestamps':[100]}], 'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':False}
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json'; b=Path(d)/'ledger.json'
   original={'version':1,'baseline_epoch':100,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
   a.write_text(json.dumps(original));b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',side_effect=[failed,failed,ok]) as scan,patch.object(m.time,'time',return_value=200):
    self.assertEqual(m.main(),0)
    self.assertEqual(scan.call_args_list[-1].args,(20,100,'statuses'))
    self.assertEqual(json.loads(a.read_text())['last_successful_scan_epoch'],200)
 def test_all_fail_preserves_state(self):
  import json, tempfile, sys
  from pathlib import Path
  import scheduled_private_scan as m
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json';b=Path(d)/'ledger.json';orig='{"version":1,"baseline_epoch":100,"last_successful_scan_epoch":100,"seen_keys":[],"pending":[]}'
   a.write_text(orig);b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',return_value={'errors':['failed'],'pages':[]}):self.assertEqual(m.main(),2)
   self.assertEqual(a.read_text(),orig)
