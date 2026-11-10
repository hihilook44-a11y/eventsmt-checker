import json
import tempfile
import unittest
from pathlib import Path
import io
import urllib.error
from unittest.mock import patch
from check import collect_pages, fetch_page, id_digest, scan, video_posts

NOW = 1_800_000_000

def post(pid, created, media_count=1, author='__eventsMT'):
    return {
        'id': str(pid), 'created_timestamp': created,
        'author': {'screen_name': author},
        'media': {'all': [
            {'type': 'video', 'url': 'https://video.twimg.com/v.mp4'}
            for _ in range(media_count)
        ]},
        'text': 'decoy text', 'url': 'https://x.com/decoy'
    }

def page(results, cursor=None, code=200):
    return {'code': code, 'results': results, 'cursor': {'bottom': cursor} if cursor else {}}

class CheckTests(unittest.TestCase):

    def test_fetch_page_retries_one_transient_transport_error(self):
        response = io.BytesIO(b'{"code":200,"results":[],"cursor":{}}')
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: False
        with patch('check.urllib.request.urlopen', side_effect=[urllib.error.URLError('redacted'), response]) as open_url, \
             patch('check.time.sleep') as sleep:
            result = fetch_page('__eventsMT')
        self.assertEqual(result['code'], 200)
        self.assertEqual(open_url.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_fetch_page_does_not_retry_client_error(self):
        error = urllib.error.HTTPError('https://example.invalid', 403, 'forbidden', {}, None)
        with patch('check.urllib.request.urlopen', side_effect=error) as open_url, \
             patch('check.time.sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                fetch_page('__eventsMT')
        self.assertEqual(open_url.call_count, 1)
        sleep.assert_not_called()
        error.close()

    def test_transient_404_retried_once(self):
        error = urllib.error.HTTPError('https://example.invalid', 404, 'not found', {}, None)
        response = io.BytesIO(b'{"code":200,"results":[],"cursor":{}}')
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: False
        with patch('check.urllib.request.urlopen', side_effect=[error, response]) as open_url, \
             patch('check.time.sleep'):
            self.assertEqual(fetch_page('__eventsMT')['code'], 200)
        self.assertEqual(open_url.call_count, 2)
        error.close()

    def test_incomplete_history_does_not_advance_watermark(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(1, NOW-30)]), state)
            before = state.read_bytes()
            counter = iter(range(3))
            def loader(h,c):
                n = next(counter)
                return page([post(10+n, NOW+1+n)], 'c'+str(n))
            with self.assertRaises(ValueError):
                scan('__eventsMT', NOW+20, loader, state)
            self.assertEqual(state.read_bytes(), before)

    def test_first_scan_is_baseline_and_logs_only_aggregates(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            result = scan('__eventsMT', NOW, lambda h,c: page([post(123456, NOW-10)]), state)
            self.assertTrue(result['baseline_created'])
            self.assertEqual(result['new_video_posts_since_last_successful_scan'], 0)
            self.assertNotIn('123456', json.dumps(result))
            self.assertNotIn('decoy', json.dumps(result))
            saved = json.loads(state.read_text())
            self.assertEqual(saved['id_sha256'], [id_digest('123456')])
            self.assertNotIn('123456', state.read_text())

    def test_new_public_id_after_successful_scan_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(10, NOW-100)]), state)
            new_page = page([post(11, NOW+10), post(10, NOW-100)])
            result = scan('__eventsMT', NOW+20, lambda h,c: new_page, state)
            self.assertEqual(result['new_video_posts_since_last_successful_scan'], 1)
            repeated = scan('__eventsMT', NOW+40, lambda h,c: new_page, state)
            self.assertEqual(repeated['new_video_posts_since_last_successful_scan'], 0)

    def test_old_unseen_ids_are_not_new_after_cursor_shift(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(10, NOW-100)]), state)
            result = scan('__eventsMT', NOW+50, lambda h,c: page([post(9, NOW-200)]), state)
            self.assertEqual(result['new_video_posts_since_last_successful_scan'], 0)

    def test_duplicate_posts_across_pages_count_once(self):
        first = page([post(1, NOW-30)], 'next')
        second = page([post(1, NOW-30), post(2, NOW-20)])
        calls=[]
        def loader(handle,cursor):
            calls.append(cursor)
            return first if cursor is None else second
        posts, pages, more = collect_pages('__eventsMT', loader)
        self.assertEqual(calls, [None, 'next'])
        self.assertEqual(len(video_posts(posts)), 2)
        self.assertEqual(pages, 2)
        self.assertFalse(more)

    def test_failed_source_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(1, NOW-30)]), state)
            before = state.read_bytes()
            with self.assertRaises(ValueError):
                scan('__eventsMT', NOW+20, lambda h,c: page([], code=500), state)
            self.assertEqual(state.read_bytes(), before)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            state.write_text('{broken')
            with self.assertRaises(ValueError):
                scan('__eventsMT', NOW, lambda h,c: page([post(2, NOW)]), state)
            self.assertEqual(state.read_text(), '{broken')

    def test_more_pages_flag_and_caps_scan(self):
        calls=[]
        def loader(h,c):
            calls.append(c)
            return page([post(len(calls), NOW)], 'cursor'+str(len(calls)))
        posts,pages,more=collect_pages('__eventsMT',loader)
        self.assertEqual(pages,3)
        self.assertEqual(len(posts),3)
        self.assertTrue(more)

    def test_main_restarts_from_first_page_after_statuses_failure(self):
        import check
        calls = []
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(1, NOW-30)]), state)
            def loader(handle, cursor, endpoint):
                calls.append((endpoint,cursor))
                if endpoint == 'statuses':
                    raise urllib.error.HTTPError('https://example.invalid', 404, 'not found', {}, None)
                return page([post(1, NOW-30)])
            with patch('check.STATE_PATH', state), patch('check.fetch_page', side_effect=loader), \
                 patch('check.time.time', return_value=NOW+20), patch('check.os.environ', {}):
                # default state_path is bound at definition; redirect scan for this test.
                original_scan = check.scan
                with patch('check.scan', side_effect=lambda h,t,loader: original_scan(h,t,loader,state)):
                    self.assertEqual(check.main(), 0)
            self.assertEqual(calls, [('statuses',None),('media',None)])
            self.assertEqual(json.loads(state.read_text())['last_successful_scan'], NOW+20)

    def test_main_failure_preserves_state(self):
        import check
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'state.json'
            scan('__eventsMT', NOW, lambda h,c: page([post(1, NOW-30)]), state)
            before = state.read_bytes()
            original_scan = check.scan
            with patch('check.fetch_page', side_effect=urllib.error.URLError('redacted')), \
                 patch('check.scan', side_effect=lambda h,t,loader: original_scan(h,t,loader,state)), \
                 patch('check.time.time', return_value=NOW+20), patch('check.os.environ', {}):
                self.assertEqual(check.main(), 1)
            self.assertEqual(state.read_bytes(), before)

    def test_audio_and_publication_stay_false(self):
        with tempfile.TemporaryDirectory() as d:
            result = scan('__eventsMT', NOW, lambda h,c: page([post(7,NOW)]), Path(d)/'state.json')
            self.assertFalse(result['candidate_audio_reviewed'])
            self.assertFalse(result['publication_performed'])

if __name__ == '__main__':
    unittest.main()
