import copy,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from git_checkpoint import encrypted_git_checkpoint,CheckpointError,push_checkpoint
from secure_scan import load_snapshot

def run(cwd,*args):return subprocess.run(['git',*args],cwd=cwd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
class GitCheckpointTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name); self.remote=self.d/'origin.git';self.repo=self.d/'work'; self.other=self.d/'other';self.f=Fernet(Fernet.generate_key());self.obj={'state':{'pending':[]},'ledger':{'published_source_ids':[]},'sensitive_marker':'hello-private'}
  run(self.d,'init','--bare','--initial-branch=main',str(self.remote));run(self.d,'clone',str(self.remote),str(self.repo));run(self.repo,'config','user.name','Test');run(self.repo,'config','user.email','test@example.invalid');(self.repo/'private_queue').mkdir();(self.repo/'private_queue'/'queue.enc').write_bytes(self.f.encrypt(b'{}'));run(self.repo,'add','.');run(self.repo,'commit','-m','baseline');run(self.repo,'push','origin','HEAD:main')
 def tearDown(self):self.tmp.cleanup()
 def test_remote_encrypted_success(self):
  encrypted_git_checkpoint(self.repo,self.f,self.obj)
  remote=run(self.remote,'show','main:private_queue/queue.enc').encode()
  self.assertNotIn(b'hello-private',remote)
  self.assertEqual(load_snapshot(self.f,self.repo/'private_queue'/'queue.enc'),self.obj)
  self.assertEqual(run(self.repo,'rev-parse','HEAD'),run(self.remote,'rev-parse','main'))
 def test_diverged_remote_preserved(self):
  run(self.d,'clone',str(self.remote),str(self.other));run(self.other,'config','user.name','Test');run(self.other,'config','user.email','test@example.invalid');(self.other/'new.txt').write_text('other');run(self.other,'add','.');run(self.other,'commit','-m','other');run(self.other,'push','origin','HEAD:main')
  before=(self.repo/'private_queue'/'queue.enc').read_bytes()
  with self.assertRaises(CheckpointError):encrypted_git_checkpoint(self.repo,self.f,self.obj)
  self.assertEqual(before,(self.repo/'private_queue'/'queue.enc').read_bytes())
 def test_push_timeout_but_remote_exact_commit_succeeds(self):
  (self.repo/'new').write_text('pending');run(self.repo,'add','new');run(self.repo,'commit','-m','pending commit')
  from git_checkpoint import cmd
  calls=[]
  def simulate(repo,*args):
   calls.append(args)
   if args[0]=='push':
    cmd(repo,*args)
    raise CheckpointError('timeout')
   return cmd(repo,*args)
  with patch('git_checkpoint.cmd',side_effect=simulate): push_checkpoint(self.repo)
  self.assertEqual(sum(x[0]=='push' for x in calls),1)
  self.assertEqual(sum(x[0]=='ls-remote' for x in calls),1)
 def test_push_timeout_remote_mismatch_fails_closed(self):
  (self.repo/'new').write_text('pending');run(self.repo,'add','new');run(self.repo,'commit','-m','not pushed')
  from git_checkpoint import cmd
  calls=[]
  def simulate(repo,*args):
   calls.append(args)
   if args[0]=='push': raise CheckpointError('timeout')
   return cmd(repo,*args)
  with patch('git_checkpoint.cmd',side_effect=simulate):
   with self.assertRaisesRegex(CheckpointError,'uncertain'):push_checkpoint(self.repo)
  self.assertEqual(sum(x[0]=='push' for x in calls),1)
 def test_push_timeout_remote_unavailable_fails_closed(self):
  with patch('git_checkpoint.cmd',side_effect=['local-head',CheckpointError('timeout'),CheckpointError('unavailable')]):
   with self.assertRaisesRegex(CheckpointError,'uncertain'):push_checkpoint(self.repo)
 def test_dirty_checkout_refuses(self):
  (self.repo/'private_queue'/'queue.enc').write_text('modified')
  with self.assertRaises(CheckpointError):encrypted_git_checkpoint(self.repo,self.f,self.obj)
if __name__=='__main__':unittest.main()
