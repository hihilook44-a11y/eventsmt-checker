import unittest
from datetime import datetime, timedelta, timezone
from candidate_recency import newest_first, recent_short
from prepare_media import eligible
from music_triage import select
from workflow_pipeline import reviewed_candidates, select_candidate

class RecencyTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime.now(timezone.utc)
  def item(n,dt):return {'post_id':str(n),'media_id':str(n),'created_at':dt}
  self.old=item(1,(self.now-timedelta(days=2)).isoformat())
  self.fresh=item(2,(self.now-timedelta(hours=2)).strftime('%a %b %d %H:%M:%S +0000 %Y'))
  self.newest=item(3,(self.now-timedelta(minutes=20)).isoformat())
  self.unknown=item(4,'not a date')
  self.pending=[self.old,self.unknown,self.fresh,self.newest]
 def test_order_and_freshness(self):
  self.assertEqual(newest_first(self.pending),[self.newest,self.fresh,self.old,self.unknown])
  self.assertTrue(recent_short(self.newest,self.now));self.assertFalse(recent_short(self.old,self.now));self.assertFalse(recent_short(self.unknown,self.now))
  future=dict(self.newest,created_at=(self.now+timedelta(hours=1)).isoformat());self.assertFalse(recent_short(future,self.now))
 def test_prepare_and_triage_prioritize_newest(self):
  snap={'state':{'pending':self.pending},'ledger':{'published_source_ids':[]}}
  self.assertEqual(eligible(snap),self.newest)
  snap['prepared_media']={f'{i}:{i}':{'has_audio':True} for i in range(1,5)}
  self.assertEqual(select(snap),self.newest)
 def test_publication_uses_only_recent_eligible(self):
  snap={'state':{'pending':self.pending},'ledger':{'published_source_ids':[]},
        'prepared_media':{f'{i}:{i}':{'has_audio':False} for i in range(1,5)},
        'candidate_deliveries':{f'{i}:{i}':{'state':'awaiting_audio_review'} for i in range(1,5)}}
  self.assertEqual(reviewed_candidates(snap,lambda *a: True),[self.newest,self.fresh])
  snap['candidate_deliveries']={}
  self.assertEqual(select_candidate(snap)[0],'3:3')
  snap['ledger']['published_source_ids']=['3']
  self.assertEqual(select_candidate(snap)[0],'2:2')
  snap['ledger']['published_source_ids']=['2','3']
  self.assertEqual(select_candidate(snap),(None,None))
if __name__=='__main__':unittest.main()
