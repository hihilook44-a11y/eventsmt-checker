import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
import secure_scan
class SecureScanTests(unittest.TestCase):
 def test_roundtrip_and_authentication(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.enc'; f=Fernet(Fernet.generate_key());x={'state':{'pending':[{'text':'sensitive-marker'}]},'ledger':{'published_source_ids':[]}}
   secure_scan.write_encrypted(f,x,p);self.assertNotIn(b'sensitive-marker',p.read_bytes());self.assertEqual(x,secure_scan.load_snapshot(f,p))
   with self.assertRaises(RuntimeError):secure_scan.load_snapshot(Fernet(Fernet.generate_key()),p)
   token=bytearray(p.read_bytes());token[len(token)//2]^=1;p.write_bytes(token)
   with self.assertRaises(RuntimeError):secure_scan.load_snapshot(f,p)
 def test_reject_invalid_structure(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.enc';f=Fernet(Fernet.generate_key());secure_scan.write_encrypted(f,{'state':{}},p)
   with self.assertRaises(RuntimeError):secure_scan.load_snapshot(f,p)
 def test_invalid_key_fails(self):
  with patch.dict(os.environ,{'PRIVATE_QUEUE_FERNET_KEY':'no'}):
   with self.assertRaises(RuntimeError):secure_scan.read_key()
if __name__=='__main__':unittest.main()
