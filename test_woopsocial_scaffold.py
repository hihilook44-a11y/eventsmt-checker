import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publication_state import PublicationState
from woopsocial_scaffold import (
    API_KEY_ENV, build_upload_request, build_youtube_draft_request, run_mocked,
)

FAKE_KEY = 'not-a-real-api-key-test-fixture'


class FakeTransport:
    is_test_double = True

    def __init__(self, response):
        self.response = response
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.response


class WoopSocialScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {API_KEY_ENV: FAKE_KEY})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_upload_request_is_multipart_and_uses_env_secret(self):
        request = build_upload_request('project-1', 'clip.mp4', b'video-bytes', 'video/mp4')
        transport = FakeTransport({'mediaId': 'mock-media-id'})
        response = run_mocked(request, transport)
        self.assertEqual(response['mediaId'], 'mock-media-id')
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(request.method, 'POST')
        self.assertTrue(request.url.endswith('/media?projectId=project-1'))
        self.assertEqual(request.headers['Authorization'], f'Bearer {FAKE_KEY}')
        self.assertIn(b'name="file"; filename="clip.mp4"', request.body)
        self.assertIn(b'video-bytes', request.body)
        self.assertNotIn(FAKE_KEY, repr(request))

    def test_missing_key_fails_without_leaking_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, API_KEY_ENV):
                build_youtube_draft_request('account', 'title', '', 'media')

    def test_youtube_payload_is_draft_only_and_matches_api_contract(self):
        request = build_youtube_draft_request('account-1', 'Example title', 'Description',
                                              'media-1', 'unlisted')
        transport = FakeTransport({'id': 'mock-post', 'schedule': {'type': 'DRAFT'}})
        result = run_mocked(request, transport)
        payload = json.loads(transport.requests[0].body)
        self.assertEqual(result['schedule']['type'], 'DRAFT')
        self.assertEqual(payload['schedule'], {'type': 'DRAFT'})
        self.assertEqual(payload['content'][0]['media'], [
            {'type': 'MEDIA_LIBRARY', 'mediaId': 'media-1'}
        ])
        self.assertEqual(payload['socialAccounts'][0], {
            'platform': 'YOUTUBE', 'socialAccountId': 'account-1',
            'title': 'Example title', 'privacy': 'unlisted'
        })
        self.assertEqual(request.headers['Content-Type'], 'application/json')

    def test_does_not_allow_unmarked_transport(self):
        request = build_upload_request('project', 'x.mp4', b'x')
        with self.assertRaisesRegex(RuntimeError, 'test transport'):
            run_mocked(request, lambda req: None)

    def test_dedup_only_marks_confirmed_success_as_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'publication.json'
            state = PublicationState(path)
            self.assertTrue(state.claim('source-post-1'))
            self.assertFalse(state.claim('source-post-1'))
            state.record_outcome('source-post-1', 'published')
            self.assertFalse(state.claim('source-post-1'))
            content = path.read_text()
            self.assertNotIn('source-post-1', content)
            self.assertEqual(list(json.loads(content)['items'].values()), ['published'])

    def test_unknown_outcome_is_not_marked_published_and_blocks_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / 'publication.json')
            self.assertTrue(state.claim('source-unknown'))
            state.record_outcome('source-unknown', 'unknown')
            self.assertFalse(state.claim('source-unknown'))
            self.assertEqual(list(json.loads(state.path.read_text())['items'].values()), ['unknown'])

    def test_confirmed_failure_is_distinct_and_can_be_claimed_again(self):
        with tempfile.TemporaryDirectory() as directory:
            state = PublicationState(Path(directory) / 'publication.json')
            self.assertTrue(state.claim('source-failed'))
            state.record_outcome('source-failed', 'failed')
            self.assertTrue(state.claim('source-failed'))
            self.assertEqual(list(json.loads(state.path.read_text())['items'].values()), ['pending'])


if __name__ == '__main__':
    unittest.main()
