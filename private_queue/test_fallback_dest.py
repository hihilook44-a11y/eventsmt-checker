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
 def test_statuses_endpoint_first_validates_before_update(self):
  import json, tempfile, sys
  from pathlib import Path
  import scheduled_private_scan as m
  ok={'errors':[],'pages':[{'page':1,'timestamps':[100]}], 'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':False}
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json'; b=Path(d)/'ledger.json'
   original={'version':1,'baseline_epoch':100,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
   a.write_text(json.dumps(original));b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',return_value=ok) as scan,patch.object(m.time,'time',return_value=200):
    self.assertEqual(m.main(),0)
    self.assertEqual(scan.call_args_list[0].args,(20,100,'statuses'))
    self.assertEqual(json.loads(a.read_text())['last_successful_scan_epoch'],200)
 def test_media_fallback_after_statuses_failure(self):
  import json, tempfile, sys
  from pathlib import Path
  import scheduled_private_scan as m
  failed={'errors':['Page 1: HTTPError: HTTP Error 404: X'],'pages':[]}
  ok={'errors':[],'pages':[{'page':1,'timestamps':[100]}], 'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':False}
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json'; b=Path(d)/'ledger.json'
   original={'version':1,'baseline_epoch':100,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
   a.write_text(json.dumps(original));b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',side_effect=[failed,ok]) as scan,patch.object(m.time,'time',return_value=200):
    self.assertEqual(m.main(),0)
    self.assertEqual(scan.call_args_list[0].args,(20,100,'statuses'))
    self.assertEqual(scan.call_args_list[1].args,(5,100,'media'))
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

 def test_partial_transport_failure_after_overlap_keeps_checkpoint(self):
  import scheduled_private_scan as m
  old={'version':1,'baseline_epoch':50,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
  scan={'errors':['Page 3: HTTPError: HTTP Error 404: Not Found'],
        'pages':[{'page':1,'timestamps':[180,160]},{'page':2,'timestamps':[130,100]}],
        'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':True}
  state,stats=m.apply_scan(scan,{'published_source_ids':[]},old,200)
  self.assertTrue(stats['partial_scan']);self.assertFalse(stats['checkpoint_advanced'])
  self.assertEqual(state['last_successful_scan_epoch'],100)
  self.assertEqual(state['last_partial_scan_epoch'],200)
 def test_partial_scan_without_overlap_is_rejected(self):
  import scheduled_private_scan as m
  old={'version':1,'baseline_epoch':50,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
  scan={'errors':['Page 3: HTTPError: HTTP Error 404: Not Found'],
        'pages':[{'page':1,'timestamps':[180]},{'page':2,'timestamps':[130]}],
        'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':True}
  with self.assertRaisesRegex(ValueError,'coverage'):
   m.apply_scan(scan,{'published_source_ids':[]},old,200)
 def test_cursor_loop_is_not_accepted_as_partial(self):
  import scheduled_private_scan as m
  old={'version':1,'baseline_epoch':50,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
  scan={'errors':['Repeated pagination cursor; stopped to avoid a loop'],
        'pages':[{'page':1,'timestamps':[180,100]}],
        'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':True}
  with self.assertRaisesRegex(ValueError,'Non-recoverable'):
   m.apply_scan(scan,{'published_source_ids':[]},old,200)
 def test_partial_main_records_checkpoint_not_advanced(self):
  import json, tempfile, sys
  from pathlib import Path
  import scheduled_private_scan as m
  partial={'errors':['Page 3: HTTPError: HTTP Error 404: Not Found'],
           'pages':[{'page':1,'timestamps':[180,160]},{'page':2,'timestamps':[130,100]}],
           'end_of_timeline_seen':False,'candidates':[],'next_cursor_available':True}
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json';b=Path(d)/'ledger.json'
   original={'version':1,'baseline_epoch':50,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}
   a.write_text(json.dumps(original));b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',return_value=partial),patch.object(m.time,'time',return_value=200):
    self.assertEqual(m.main(),0)
   saved=json.loads(a.read_text())
   self.assertEqual(saved['last_successful_scan_epoch'],100)
   self.assertEqual(saved['last_partial_scan_epoch'],200)

class PartialFallbackTests(unittest.TestCase):
 def run_scans(self,scans):
  import json,tempfile,sys
  from pathlib import Path
  import scheduled_private_scan as m
  with tempfile.TemporaryDirectory() as d:
   a=Path(d)/'state.json';b=Path(d)/'ledger.json'
   a.write_text(json.dumps({'version':1,'baseline_epoch':50,'last_successful_scan_epoch':100,'seen_keys':[],'pending':[]}));b.write_text('{"published_source_ids": []}')
   with patch.object(sys,'argv',['scan','--state',str(a),'--ledger',str(b)]),patch.object(m,'run',side_effect=scans) as call,patch.object(m.time,'time',return_value=200):
    result=m.main()
   return result,json.loads(a.read_text()),call.call_count
 def test_later_clean_route_advances_checkpoint_after_partial(self):
  partial={'errors':['Page 2: HTTPError: HTTP Error 404: Not Found'],'pages':[{'page':1,'timestamps':[100]}], 'candidates':[],'next_cursor_available':True,'end_of_timeline_seen':False}
  clean={'errors':[],'pages':[{'page':1,'timestamps':[100]}], 'candidates':[],'next_cursor_available':True,'end_of_timeline_seen':False}
  result,s,count=self.run_scans([partial,clean]);self.assertEqual(result,0);self.assertEqual(s['last_successful_scan_epoch'],200);self.assertEqual(count,2)
 def test_all_partial_or_failed_preserves_old_checkpoint(self):
  partial={'errors':['Page 2: HTTPError: HTTP Error 404: Not Found'],'pages':[{'page':1,'timestamps':[100]}], 'candidates':[],'next_cursor_available':True,'end_of_timeline_seen':False}
  failed={'errors':['Page 1: HTTPError: HTTP Error 404: Not Found'],'pages':[], 'candidates':[],'next_cursor_available':False}
  result,s,count=self.run_scans([partial,failed,failed]);self.assertEqual(result,0);self.assertEqual(s['last_successful_scan_epoch'],100);self.assertEqual(count,3)
 def test_clean_fallback_retains_and_deduplicates_partial_candidates(self):
  item={'post_id':'123','media_id':'456','created_at':'1970-01-01T00:02:30+00:00','music_checked':False,'published':False}
  partial={'errors':['Page 2: HTTPError: HTTP Error 404: Not Found'],'pages':[{'page':1,'timestamps':[100]}], 'candidates':[item],'next_cursor_available':True,'end_of_timeline_seen':False}
  clean={'errors':[],'pages':[{'page':1,'timestamps':[100]}], 'candidates':[item],'next_cursor_available':True,'end_of_timeline_seen':False}
  result,s,count=self.run_scans([partial,clean]);self.assertEqual(result,0);self.assertEqual(len(s['pending']),1);self.assertEqual(s['pending'][0]['post_id'],'123');self.assertEqual(s['last_successful_scan_epoch'],200)
