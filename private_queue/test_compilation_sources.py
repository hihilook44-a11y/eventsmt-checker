import unittest
from copy import deepcopy
from compilation_sources import candidates, retain_reviewed_sources
import test_compilation_assessment as fixture

class SourceTests(unittest.TestCase):
 def test_retention_before_queue_removal_is_independent_of_shorts(self):
  s={'state':{'pending':[{'post_id':'1','media_id':'2','video_url':'url'}]},'audio_reviews':{'1:2':{'signed':'proof'}},'prepared_media':{'1:2':{'sha256':'a'*64}},'ledger':{'published_source_ids':['1']}}
  original=deepcopy(s)
  retain_reviewed_sources(s);s['state']['pending']=[]
  self.assertEqual(candidates(s), original['state']['pending'])
  self.assertEqual(s['audio_reviews'],original['audio_reviews'])
  self.assertEqual(s['ledger'],original['ledger'])
 def test_unreviewed_not_archived(self):
  s={'state':{'pending':[{'post_id':'1','media_id':'2'}]}}
  retain_reviewed_sources(s);self.assertEqual(s['compilation_sources'],{})
 def test_duplicate_identity_is_merged_once(self):
  i={'post_id':'1','media_id':'2','video_url':'url'}
  self.assertEqual(len(candidates({'state':{'pending':[i]},'compilation_sources':{'1:2':i}})),1)
 def test_archive_identity_mismatch_rejected(self):
  with self.assertRaises(ValueError):candidates({'state':{'pending':[]},'compilation_sources':{'1:2':{'post_id':'9','media_id':'9'}}})
 def test_published_short_still_requires_actual_audio_proof(self):
  f=fixture.Tests();f.setUp()
  f.s['compilation_sources']={'1:2':f.s['state']['pending'].pop(0)}
  self.assertEqual(f.a()['reviewed_clips'],2)
  f.s['audio_reviews']['1:2']={'ok':0}
  self.assertEqual(f.a()['reviewed_clips'],1)
 def test_previously_compiled_archived_source_excluded(self):
  f=fixture.Tests();f.setUp()
  f.s['compilation_sources']={'1:2':f.s['state']['pending'].pop(0)}
  f.s['compilation_attempts']={'old':{'state':'published','source_keys':['1:2'],'source_sha256':[f.s['prepared_media']['1:2']['sha256']]}}
  self.assertEqual(f.a()['reviewed_clips'],1)
if __name__=='__main__':unittest.main()
