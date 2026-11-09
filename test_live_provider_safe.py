import sys, unittest
from unittest.mock import patch
sys.path.insert(0,'private_queue')
import test_live_provider as t

class Stub:
    def projects(self): return [{'id':'project'}]
    def call(self,method,path):
        if path.startswith('/social-accounts'): return [{'platform':'YOUTUBE','status':'CONNECTED','id':'account'}]
        if path.startswith('/media?'): return {'media':[{'id':'m','projectId':'project'}]}
        raise AssertionError(path)
    def upload(self,project,data): return 'm'
    def draft(self,account,title,description,media):
        assert (account,media)==('account','m'); return 'd'
    def post(self,id):return {'id':id,'projectId':'project','schedule':{'type':'DRAFT'},'socialAccountPosts':[{'socialAccountId':'account','deliveryStatus':'NOT_STARTED'}]}
class Safety(unittest.TestCase):
    def test_single_use_reconciliation(self):
        s={};p=Stub();t.init(s,p)
        with self.assertRaises(ValueError):t.init(s,p)
        t.upload(s,p,b'test');t.prepare_draft(s,p);t.draft(s,p);t.verify(s,p)
        self.assertEqual(s['integration_test']['state'],'verified_draft')
        with self.assertRaises(ValueError):t.upload(s,p,b'test')
        with self.assertRaises(ValueError):t.draft(s,p)
    def test_blocks_multiple_targets(self):
        p=Stub();p.projects=lambda:[{'id':'one'},{'id':'two'}]
        with self.assertRaises(ValueError):t.init({},p)
    def test_blocks_unfound_media(self):
        s={'integration_test':{'state':'uploaded','project':'project','media_id':'missing'}}
        with self.assertRaises(ValueError):t.prepare_draft(s,Stub())
if __name__=='__main__':unittest.main()
