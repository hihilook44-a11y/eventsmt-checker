import hashlib,subprocess,tempfile,unittest
from pathlib import Path
from cryptography.fernet import Fernet
from secure_scan import load_snapshot
from git_checkpoint import encrypted_git_checkpoint
from workflow_pipeline import run_candidate,select_candidate
from candidate_pipeline import CandidatePipeline,PipelineError

def git(cwd,*args):
    return subprocess.run(['git',*args],cwd=cwd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
class FakeProvider:
    def __init__(self,fail=False):self.uploads=0;self.drafts=0;self.fail=fail
    def upload(self,project,data):
        self.uploads+=1
        if self.fail:raise TimeoutError('unknown outcome')
        return 'synthetic-media'
    def call(self,method,path):return {'media':[{'id':'synthetic-media','projectId':'synthetic-project'}]}
    def draft(self,account,title,description,media):self.drafts+=1;return 'synthetic-post'
    def post(self,id):return {'id':id,'projectId':'synthetic-project','schedule':{'type':'DRAFT'},'socialAccountPosts':[{'socialAccountId':'synthetic-account','deliveryStatus':'NOT_STARTED'}]}
class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.d=Path(self.t.name);self.remote=self.d/'remote.git';self.repo=self.d/'repo';self.f=Fernet(Fernet.generate_key());self.data=b'synthetic-only-media';self.key='12:34'
        git(self.d,'init','--bare','--initial-branch=main',str(self.remote));git(self.d,'clone',str(self.remote),str(self.repo));git(self.repo,'config','user.name','Test');git(self.repo,'config','user.email','test@example.invalid');(self.repo/'private_queue').mkdir()
        self.s={'state':{'pending':[{'post_id':'12','media_id':'34'}]},'ledger':{'published_source_ids':[]},'prepared_media':{self.key:{'sha256':hashlib.sha256(self.data).hexdigest()}}}
        from secure_scan import write_encrypted
        write_encrypted(self.f,self.s,self.repo/'private_queue'/'queue.enc');git(self.repo,'add','.');git(self.repo,'commit','-m','baseline');git(self.repo,'push','origin','HEAD:main')
    def tearDown(self):self.t.cleanup()
    def cp(self,s):encrypted_git_checkpoint(self.repo,self.f,s)
    def saved(self):
        raw=subprocess.run(['git','show','main:private_queue/queue.enc'],cwd=self.remote,check=True,stdout=subprocess.PIPE).stdout
        return __import__('json').loads(self.f.decrypt(raw))
    def test_select_candidate_prioritizes_low_risk_without_bypassing_gate(self):
        from unittest.mock import patch
        from music_triage import MODEL_VERSION
        a={'post_id':'10','media_id':'10'}; b={'post_id':'20','media_id':'20'}
        digest='a'*64
        proof={'model_version':MODEL_VERSION,'sha256':digest,'classification':'low_risk','is_clearance':False,'assessment_scope':'entire_audio','yamnet_peak':.01,'efficientat_peak':.02,'duration_seconds':10}
        snapshot={'state':{'pending':[a,b]},'ledger':{'published_source_ids':[]},'prepared_media':{'10:10':{'sha256':'b'*64,'has_audio':True},'20:20':{'sha256':digest,'has_audio':True}},'music_triage':{'20:20':proof}}
        with patch.dict('os.environ',{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}): self.assertEqual(select_candidate(snapshot)[0],'20:20')
        with patch.dict('os.environ',{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'false'}): self.assertEqual(select_candidate(snapshot)[0],'10:10')
        snapshot['ledger']['published_source_ids']=['20']
        with patch.dict('os.environ',{'AUTOMATIC_AUDIO_RISK_ACCEPTED':'true'}): self.assertEqual(select_candidate(snapshot)[0],'10:10')
    def test_full_synthetic_draft_and_remote_checkpoints(self):
        p=FakeProvider();x=load_snapshot(self.f,self.repo/'private_queue'/'queue.enc')
        status=run_candidate(x,self.cp,p,self.key,self.data,'synthetic-project','synthetic-account','test','',True,lambda i,d,p:p is True)
        self.assertEqual(status,'verified_draft');self.assertEqual(self.saved()['candidate_deliveries'][self.key]['state'],'verified_draft');self.assertEqual((p.uploads,p.drafts),(1,1));self.assertEqual(self.saved()['ledger']['published_source_ids'],[])
        with self.assertRaises(PipelineError):run_candidate(load_snapshot(self.f,self.repo/'private_queue'/'queue.enc'),self.cp,p,self.key,self.data,'synthetic-project','synthetic-account','test','',True,lambda *a:True)
        self.assertEqual((p.uploads,p.drafts),(1,1))
    def test_unknown_upload_persists_and_blocks_restart(self):
        p=FakeProvider(True);x=load_snapshot(self.f,self.repo/'private_queue'/'queue.enc')
        with self.assertRaises(TimeoutError):run_candidate(x,self.cp,p,self.key,self.data,'synthetic-project','synthetic-account','test','',True,lambda *a:True)
        self.assertEqual(self.saved()['candidate_deliveries'][self.key]['state'],'upload_uncertain')
        with self.assertRaises(PipelineError):run_candidate(load_snapshot(self.f,self.repo/'private_queue'/'queue.enc'),self.cp,p,self.key,self.data,'synthetic-project','synthetic-account','test','',True,lambda *a:True)
        self.assertEqual((p.uploads,p.drafts),(1,0))
    def test_production_review_gate_never_uploads(self):
        p=FakeProvider();x=load_snapshot(self.f,self.repo/'private_queue'/'queue.enc')
        self.assertEqual(run_candidate(x,self.cp,p,self.key,self.data), 'awaiting_audio_review')
        self.assertEqual(self.saved()['candidate_deliveries'][self.key]['state'],'awaiting_audio_review');self.assertEqual((p.uploads,p.drafts),(0,0))
if __name__=='__main__':unittest.main()
