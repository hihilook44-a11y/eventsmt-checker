#!/usr/bin/env python3
"""Minimal, fail-closed Zernio transport for reviewed YouTube video scheduling.

The caller must supply exact-byte audio-review approval, idempotent queue state,
profile/account IDs, and a profile-scoped API key. This module never logs credentials,
signed upload URLs, request bodies, or provider response bodies.
"""
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = 'https://zernio.com/api/v1'


class ZernioError(RuntimeError):
    pass


class ZernioProvider:
    name = 'zernio'
    def __init__(self, key=None, profile=None, account=None, opener=None):
        self.key = (key if key is not None else os.environ.get('ZERNIO_API_KEY', '')).strip()
        self.profile = (profile if profile is not None else os.environ.get('ZERNIO_PROFILE_ID', '')).strip()
        self.account = (account if account is not None else os.environ.get('ZERNIO_YOUTUBE_ACCOUNT_ID', '')).strip()
        if not self.key:
            raise ValueError('ZERNIO_API_KEY missing')
        if len(self.profile) != 24 or any(c not in '0123456789abcdefABCDEF' for c in self.profile):
            raise ValueError('ZERNIO_PROFILE_ID invalid')
        if not self.account or len(self.account) > 128:
            raise ValueError('ZERNIO_YOUTUBE_ACCOUNT_ID invalid')
        self.opener = opener or urllib.request.build_opener()

    def _request(self, method, url, body=None, content_type=None, headers=None, authorized=True, accepted=(200, 201)):
        if not url.startswith('https://'):
            raise ZernioError('HTTPS required')
        h = {'Accept': 'application/json'}
        if authorized:
            h['Authorization'] = 'Bearer ' + self.key
        if content_type:
            h['Content-Type'] = content_type
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=90) as response:
                raw = response.read()
                if response.status not in accepted:
                    raise ZernioError('unexpected HTTP status')
                if not raw:
                    return response.status, {}
                try:
                    return response.status, json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ZernioError('invalid JSON response') from None
        except urllib.error.HTTPError as exc:
            # Surface only a provider error class from a strict allowlist. Never log its
            # message/body, which may contain IDs, submitted text, or signed URLs.
            error_type = None
            try:
                payload = json.loads(exc.read(8192))
                candidate = payload.get('type') if isinstance(payload, dict) else None
                if candidate in {'invalid_request_error', 'authentication_error', 'permission_error',
                                 'not_found', 'rate_limit_error', 'platform_error', 'api_error'}:
                    error_type = candidate
            except (OSError, ValueError, UnicodeDecodeError):
                pass
            suffix = ' ' + error_type if error_type else ''
            raise ZernioError('HTTP ' + str(exc.code) + suffix) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if isinstance(exc, ZernioError):
                raise
            raise ZernioError('transport error') from None

    def _api(self, method, path, payload=None, headers=None):
        if not path.startswith('/') or path.startswith('//') or '\r' in path or '\n' in path:
            raise ValueError('invalid path')
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        clean_path = path.split('?', 1)[0]
        if clean_path == '/accounts':
            endpoint = 'accounts'
        elif clean_path == '/media/presign':
            endpoint = 'media/presign'
        elif clean_path == '/posts' or clean_path.startswith('/posts/'):
            endpoint = 'posts'
        else:
            endpoint = 'API'
        try:
            accepted=(200, 201, 202, 207) if clean_path == '/posts' and method == 'POST' else (200, 201)
            _, result = self._request(method, BASE + path, body, 'application/json' if body is not None else None, headers, accepted=accepted)
        except ZernioError as exc:
            # Include only a fixed endpoint label and sanitized error, never query, IDs,
            # provider bodies, credentials, or signed URLs.
            raise ZernioError(f'{method} {endpoint}: {exc}') from None
        return result

    def verify_destination(self, profile, account):
        if profile != self.profile or account != self.account:
            return False
        query = urllib.parse.urlencode({'profileId': profile, 'platform': 'youtube', 'status': 'connected', 'limit': 100})
        result = self._api('GET', '/accounts?' + query)
        rows = result.get('accounts')
        if not isinstance(rows, list):
            raise ZernioError('account list unavailable')
        matches = [row for row in rows if row.get('_id', row.get('id')) == account
                   and str(row.get('platform', '')).lower() == 'youtube'
                   and str(row.get('status', 'connected')).lower() == 'connected'
                   and row.get('enabled', True) is not False]
        return len(matches) == 1

    def upload(self, project, content, filename='reviewed-video.mp4'):
        if project != self.profile or not isinstance(content, bytes) or not content or len(content) > 5_000_000_000:
            raise ValueError('invalid project or media')
        presign = self._api('POST', '/media/presign', {
            'filename': filename, 'contentType': 'video/mp4', 'size': len(content)
        })
        upload_url, public_url = presign.get('uploadUrl'), presign.get('publicUrl')
        if not isinstance(upload_url, str) or not upload_url.startswith('https://'):
            raise ZernioError('upload URL unavailable')
        parsed = urllib.parse.urlparse(public_url or '')
        if parsed.scheme != 'https' or parsed.hostname != 'media.zernio.com' or not parsed.path.endswith('.mp4'):
            raise ZernioError('public media URL invalid')
        # The one-time storage URL is used without an Authorization header.
        self._request('PUT', upload_url, content, 'video/mp4', authorized=False, accepted=(200, 201, 204))
        return public_url

    def verify_media(self, project, media_url):
        return (project == self.profile and isinstance(media_url, str)
                and media_url.startswith('https://media.zernio.com/')
                and media_url.endswith('.mp4'))

    def publish_scheduled(self, account, title, description, media_url, scheduled_for, idempotency_key):
        if account != self.account or not title or not media_url.startswith('https://media.zernio.com/'):
            raise ValueError('destination or media mismatch')
        if len(title) > 100:
            title = title[:100]
        payload = {
            'content': description,
            'mediaItems': [{'type': 'video', 'url': media_url}],
            'platforms': [{
                'platform': 'youtube',
                'accountId': account,
                'scheduledFor': scheduled_for,
                'platformSpecificData': {'title': title, 'visibility': 'public'}
            }],
            'timezone': 'Europe/London',
            'metadata': {'eventsmtPipelineKey': idempotency_key}
        }
        result = self._api('POST', '/posts', payload, {'Idempotency-Key': idempotency_key})
        post = result.get('post') if isinstance(result, dict) else None
        post_id = post.get('_id') if isinstance(post, dict) else None
        # The create response may omit or incompletely populate platform targets.
        # Persist its durable ID only; workflow reconciliation immediately GETs that
        # ID and independently verifies the configured YouTube account before it
        # records a schedule or publication. An absent/mismatched read-back remains
        # unresolved and blocks any different delivery.
        if not isinstance(post_id, str) or not post_id or post.get('status') not in ('scheduled', 'publishing', 'published', 'partial', 'failed'):
            raise ZernioError('scheduled post not confirmed')
        return post_id

    def post(self, post_id):
        result = self._api('GET', '/posts/' + urllib.parse.quote(post_id, safe=''))
        post = result.get('post') if isinstance(result, dict) else None
        if not isinstance(post, dict) or post.get('_id') != post_id:
            raise ZernioError('post readback mismatch')
        statuses = {'published': 'PUBLISHED', 'scheduled': 'SCHEDULED', 'pending': 'SCHEDULED',
                    'publishing': 'SENDING', 'processing': 'SENDING', 'failed': 'FAILED',
                    'cancelled': 'FAILED', 'uploading': 'SENDING'}
        rows = []
        for platform in post.get('platforms', []):
            rows.append({
                'socialAccountId': platform.get('accountId'),
                'platform': platform.get('platform'),
                'deliveryStatus': statuses.get(str(platform.get('status', '')).lower(), 'OTHER'),
                'externalPostId': platform.get('platformPostId'),
                'externalPostUrl': platform.get('platformPostUrl'),
            })
        # Normalize only the documented provider fields; expected profile is the
        # scope enforced by this key and configured target, not a claimed API field.
        return {'id': post_id, 'projectId': self.profile,
                'schedule': {'type': 'SCHEDULED' if str(post.get('status', '')).lower() == 'scheduled' else str(post.get('status', '')).upper()},
                'socialAccountPosts': rows}


def stable_idempotency_key(account, candidate, media_sha256):
    """A stable UUID for exactly one candidate-byte/account delivery."""
    raw = f'eventsmt:{account}:{candidate}:{media_sha256}'
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))
