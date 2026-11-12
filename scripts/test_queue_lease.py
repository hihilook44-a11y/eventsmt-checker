import os,subprocess,tempfile,unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parent/'queue_lease.py'

def cmd(cwd,*args):return subprocess.run(args,cwd=cwd,text=True,capture_output=True)
class LeaseTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.remote=self.root/'remote.git';self.a=self.root/'a';self.b=self.root/'b'
  for cwd,args in [(self.root,['git','init','--bare','--initial-branch=main',str(self.remote)]),(self.root,['git','clone',str(self.remote),str(self.a)]),(self.a,['git','config','user.email','test@example.test']),(self.a,['git','config','user.name','test']),(self.a,['git','commit','--allow-empty','-m','base']),(self.a,['git','push','origin','HEAD:main']),(self.root,['git','clone',str(self.remote),str(self.b)])]:
   r=cmd(cwd,*args);self.assertEqual(r.returncode,0,r.stderr)
 def tearDown(self):self.tmp.cleanup()
 def lease(self,repo,operation,token):return cmd(repo,'python3',str(SCRIPT),operation,'--token',str(token))
 def test_exclusive_and_release(self):
  a=self.root/'a.token';b=self.root/'b.token'
  self.assertEqual(self.lease(self.a,'acquire',a).returncode,0)
  self.assertNotEqual(self.lease(self.b,'acquire',b).returncode,0)
  self.assertFalse(b.exists());self.assertEqual(self.lease(self.a,'release',a).returncode,0)
  self.assertEqual(self.lease(self.b,'acquire',b).returncode,0);self.assertEqual(self.lease(self.b,'release',b).returncode,0)
 def test_wrong_token_cannot_release(self):
  a=self.root/'a.token';b=self.root/'b.token';self.assertEqual(self.lease(self.a,'acquire',a).returncode,0)
  b.write_text('1'*40);self.assertNotEqual(self.lease(self.b,'release',b).returncode,0);self.assertTrue(a.exists());self.assertTrue(b.exists())
  self.assertEqual(self.lease(self.a,'release',a).returncode,0)
 def test_existing_token_stops_new_acquire(self):
  a=self.root/'a.token';a.write_text('1'*40);self.assertNotEqual(self.lease(self.a,'acquire',a).returncode,0)
if __name__=='__main__':unittest.main()
