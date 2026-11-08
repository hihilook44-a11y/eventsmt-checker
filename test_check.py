import unittest
from check import count_page, scan_pages, LOOKBACK_SECONDS

NOW = 1_800_000_000

def post(pid, created, media_count=1, author='__eventsMT'):
    return {
        'id': str(pid), 'created_timestamp': created,
        'author': {'screen_name': author},
        'media': {'all': [
            {'type': 'video', 'url': 'https://video.twimg.com/v.mp4'}
            for _ in range(media_count)
        ]},
        # Decoy fields must never leak into counts/output.
        'text': 'private decoy', 'url': 'https://x.com/private-decoy'
    }

class CheckTests(unittest.TestCase):
    def test_recent_window_and_old_items(self):
        seen=set()
        data={'code':200,'results':[
            post(1, NOW-60), post(2, NOW-LOOKBACK_SECONDS-1),
            post(3, NOW+1), post(4, NOW-120, 2, author='someone_else')
        ]}
        self.assertEqual(count_page(data,'__eventsMT',seen,NOW,LOOKBACK_SECONDS),(3,1))

    def test_duplicates_across_pages_count_once_in_one_run(self):
        first={'code':200,'results':[post(1,NOW-30)],'cursor':{'bottom':'next'}}
        second={'code':200,'results':[post(1,NOW-30),post(2,NOW-30)],'cursor':{}}
        calls=[]
        def loader(handle,cursor):
            calls.append(cursor)
            return first if cursor is None else second
        result=scan_pages('__eventsMT',NOW,loader)
        self.assertEqual(calls,[None,'next'])
        self.assertEqual(result['videos_seen'],2)
        self.assertEqual(result['videos_posted_within_lookback'],2)

    def test_aggregate_output_contains_no_post_details(self):
        data={'code':200,'results':[post(123456,NOW-30)],'cursor':{}}
        result=scan_pages('__eventsMT',NOW,lambda h,c:data)
        serialized=str(result)
        self.assertNotIn('123456',serialized)
        self.assertNotIn('private decoy',serialized)
        self.assertNotIn('video.twimg.com',serialized)
        self.assertFalse(result['candidate_audio_reviewed'])
        self.assertFalse(result['publication_performed'])

    def test_invalid_source_fails_closed(self):
        with self.assertRaises(ValueError):
            count_page({'code':500,'results':[]},'__eventsMT',set(),NOW,LOOKBACK_SECONDS)

if __name__=='__main__':
    unittest.main()
