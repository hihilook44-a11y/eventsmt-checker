import unittest
from workflow_pipeline import reconcile_known_deliveries, delivery_in_flight, reconciliation_summary
from candidate_pipeline import PipelineError
from zernio_adapter import ZernioError
class P:
 def __init__(self,status):self.status=status;self.calls=[]
 def post(self,id):self.calls.append(id);return {'id':id,'projectId':'p','socialAccountPosts':[{'socialAccountId':'a','deliveryStatus':self.status}]}
def snapshot():return {'state':{'pending':[]},'ledger':{'published_source_ids':[]},'candidate_deliveries':{'12:34':{'state':'delivery_recorded','post_id':'post','project':'p','account':'a'}}}

class NoMatchP:
 def __init__(self,error):self.error=error;self.calls=[]
 def post(self,id):self.calls.append(id);raise self.error

class Tests(unittest.TestCase):
 def test_reconciliation_summary_never_exposes_ids(self):
  s=snapshot();s['candidate_deliveries']['12:34']['provider']='zernio';s['candidate_deliveries']['12:34']['post_id']='private-post-id-secret'
  summary=reconciliation_summary(s)
  self.assertEqual(summary,{'provider=zernio state=delivery_recorded post_id=other':1})
  self.assertNotIn('private-post-id-secret',repr(summary))
 def test_known_delivery_recorded_on_success_only(self):
  s=snapshot();writes=[];p=P('PUBLISHED');reconcile_known_deliveries(s,lambda s:writes.append(1),p)
  self.assertEqual(s['ledger']['published_source_ids'],['12']);self.assertEqual(s['candidate_deliveries']['12:34']['state'],'published');self.assertEqual(len(writes),1)
 def test_pending_and_failed_are_not_retried_or_recorded(self):
  for status in ['NOT_STARTED','SENDING','FAILED','SCHEDULED']:
   s=snapshot();s['candidate_deliveries']['12:34']['provider']='woopsocial';writes=[]
   reconcile_known_deliveries(s,lambda s:writes.append(1),P(status));self.assertEqual(s['ledger']['published_source_ids'],[]);self.assertEqual(writes,[])
 def test_zernio_scheduled_receipt_is_checkpointed(self):
  s=snapshot();s['candidate_deliveries']['12:34']['provider']='zernio';writes=[];p=P('SCHEDULED')
  reconcile_known_deliveries(s,lambda s:writes.append(1),p,{'zernio':p})
  self.assertEqual(s['candidate_deliveries']['12:34']['state'],'delivery_scheduled');self.assertEqual(writes,[1])
 def test_missing_post_id_is_not_guessed(self):
  s=snapshot();s['candidate_deliveries']['12:34'].pop('post_id');p=P('PUBLISHED');reconcile_known_deliveries(s,lambda s:None,p);self.assertEqual(p.calls,[])
 def test_in_flight_prevents_another_delivery(self):
  for state in ['upload_uncertain','draft_uncertain','delivery_uncertain','delivery_recorded']:
   s=snapshot();s['candidate_deliveries']['12:34']['state']=state
   self.assertTrue(delivery_in_flight(s))
  for state in ['published','awaiting_audio_review','upload_complete']:
   s=snapshot();s['candidate_deliveries']['12:34']['state']=state
   self.assertFalse(delivery_in_flight(s))
 def test_wrong_destination_fails_closed(self):
  s=snapshot();p=P('PUBLISHED');p.post=lambda id:{'id':id,'projectId':'p','socialAccountPosts':[{'socialAccountId':'other','deliveryStatus':'PUBLISHED'}]}
  with self.assertRaises(PipelineError):reconcile_known_deliveries(s,lambda s:None,p)
  self.assertEqual(s['ledger']['published_source_ids'],[])
 def test_legacy_provider_is_inferred_only_after_exact_readback(self):
  s=snapshot();writes=[];z=NoMatchP(ZernioError('GET posts: HTTP 400 invalid_request_error'));w=P('SENDING')
  reconcile_known_deliveries(s,lambda state:writes.append(1),z,{'zernio':z,'woopsocial':w})
  self.assertEqual(s['candidate_deliveries']['12:34']['provider'],'woopsocial')
  self.assertEqual((len(z.calls),len(w.calls)),(1,1));self.assertEqual(writes,[1])
 def test_legacy_provider_unresolved_stays_blocked(self):
  s=snapshot();writes=[];z=NoMatchP(ZernioError('GET posts: HTTP 400 invalid_request_error'));w=NoMatchP(Exception('HTTP 404'))
  with self.assertRaisesRegex(PipelineError,'provider unresolved'):
   reconcile_known_deliveries(s,lambda state:writes.append(1),z,{'zernio':z,'woopsocial':w})
  self.assertNotIn('provider',s['candidate_deliveries']['12:34']);self.assertEqual(writes,[])
  self.assertTrue(delivery_in_flight(s))
 def test_legacy_provider_transport_error_does_not_fallback_or_write(self):
  s=snapshot();writes=[];z=NoMatchP(Exception('transport error'));w=P('PUBLISHED')
  with self.assertRaisesRegex(PipelineError,'lookup unavailable'):
   reconcile_known_deliveries(s,lambda state:writes.append(1),z,{'zernio':z,'woopsocial':w})
  self.assertEqual(w.calls,[]);self.assertEqual(writes,[])
if __name__=='__main__':unittest.main()
