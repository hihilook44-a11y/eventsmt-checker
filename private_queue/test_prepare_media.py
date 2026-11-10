import copy,unittest
import prepare_media as p

def fixture():
    return {'state':{'pending':[{'post_id':'12','media_id':'34','video_url':'https://video.twimg.com/a.mp4'}]},'ledger':{'published_source_ids':[]}}
class Tests(unittest.TestCase):
    def test_success_is_review_only(self):
        s=fixture(); ok=p.prepare(s,lambda url:b'media',lambda path:{'format':{'duration':'5.2'},'streams':[{'codec_type':'video'},{'codec_type':'audio'}]})
        self.assertTrue(ok); self.assertEqual(s['prepared_media']['12:34']['status'],'awaiting_audio_review'); self.assertTrue(s['prepared_media']['12:34']['has_audio']);self.assertFalse(p.eligible(s))
    def test_published_excluded(self):
        s=fixture();s['ledger']['published_source_ids']=['12'];self.assertIsNone(p.eligible(s))
    def test_rejects_wrong_host(self):
        for url in ['http://video.twimg.com/a','https://video.twimg.com.evil.com/a','https://user@video.twimg.com/a','https://video.twimg.com:444/a']:
            with self.assertRaises(ValueError):p.check_url(url)
    def test_failure_does_not_change_snapshot(self):
        s=fixture(); before=copy.deepcopy(s)
        with self.assertRaises(ValueError):p.prepare(s,lambda url:b'bad',lambda path:{'format':{'duration':'0'},'streams':[]})
        self.assertEqual(s,before)
    def test_slow_media_read_has_overall_deadline_and_cleans_up(self):
        import time,signal
        from unittest.mock import patch
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def geturl(self):return 'https://video.twimg.com/a'
            def read(self,size):time.sleep(5);return b'data'
        class Opener:
            def open(self,*args,**kwargs):return Response()
        original=signal.alarm
        old=signal.getsignal(signal.SIGALRM)
        def short(n):return original(1 if n else 0)
        with patch.object(p.signal,'alarm',side_effect=short):
            with self.assertRaises(TimeoutError):p.get_media('https://video.twimg.com/a',Opener())
        self.assertIs(signal.getsignal(signal.SIGALRM),old)
        self.assertEqual(original(0),0)
    def test_duplicate_preparation_excluded(self):
        s=fixture();s['prepared_media']={'12:34':{'status':'awaiting_audio_review'}};self.assertIsNone(p.eligible(s))
if __name__=='__main__':unittest.main()
