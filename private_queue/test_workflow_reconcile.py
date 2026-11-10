import unittest
from workflow_pipeline import reconcile_known_deliveries, delivery_in_flight
from candidate_pipeline import PipelineError
class P:
 def __init__(self,status):self.status=status;self.calls=[]
 def post(self,id):self.calls.append(id);return {'id':id,'projectId':'p','socialAccountPosts':[{'socialAccountId':'a','deliveryStatus':self.status}]}
def snapshot():return {'state':{'pending':[]},'ledger':{'published_source_ids':[]},'candidate_deliveries':{'12:34':{'state':'delivery_recorded','post_id':'post','project':'p','account':'a'}}}
class Tests(unittest.TestCase):
 def test_known_delivery_recorded_on_success_only(self):
  s=snapshot();writes=[];p=P('PUBLISHED');reconcile_known_deliveries(s,lambda s:writes.append(1),p)
  self.assertEqual(s['ledger']['published_source_ids'],['12']);self.assertEqual(s['candidate_deliveries']['12:34']['state'],'published');self.assertEqual(len(writes),1)
 def test_pending_and_failed_are_not_retried_or_recorded(self):
  for status in ['NOT_STARTED','SENDING','FAILED','SCHEDULED']:
   s=snapshot();writes=[];reconcile_known_deliveries(s,lambda s:writes.append(1),P(status));self.assertEqual(s['ledger']['published_source_ids'],[]);self.assertEqual(writes,[])
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
if __name__=='__main__':unittest.main()
