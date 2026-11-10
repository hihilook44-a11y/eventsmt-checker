import copy, unittest
import reconcile_one_known as r
from zernio_adapter import stable_idempotency_key
class P:
    profile='p';account='a'
class Match(unittest.TestCase):
 def setUp(self):
    self.key=r.SOURCE_ID+':123'
    rec={'state':'delivery_uncertain','provider':'zernio','project':'p','account':'a','media_id':'https://media.zernio.com/test.mp4','sha256':'abc'}
    rec['idempotency_key']=stable_idempotency_key('a',self.key,'abc')
    self.s={'candidate_deliveries':{self.key:rec}}
    self.raw={'post':{'_id':r.POST_ID,'content':'hello https://x.com/__eventsMT/status/'+r.SOURCE_ID,'metadata':{'eventsmtPipelineKey':rec['idempotency_key']},'mediaItems':[{'url':rec['media_id']}],'platforms':[{'accountId':'a','platform':'youtube','status':'published','platformPostId':'video'}]}}
 def test_match(self): self.assertEqual(r.match_record(self.s,P(),self.raw)[0],self.key)
 def test_bad_evidence_rejected(self):
    for field,value in [('content','other'),('_id','other'),('metadata',{}),('mediaItems',[]),('platforms',[])]:
       bad=copy.deepcopy(self.raw);bad['post'][field]=value
       with self.assertRaises(ValueError):r.match_record(self.s,P(),bad)
 def test_mismatched_record_rejected(self):
    for field,value in [('provider','other'),('state','published'),('post_id','already'),('project','other'),('account','other'),('media_id','other'),('idempotency_key','other')]:
       s=copy.deepcopy(self.s);s['candidate_deliveries'][self.key][field]=value
       with self.assertRaises(ValueError):r.match_record(s,P(),self.raw)
if __name__=='__main__':unittest.main()
