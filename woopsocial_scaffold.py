"""Safe WoopSocial REST request builders; intentionally not wired to a publisher.

API keys are read only from WOOPSOCIAL_API_KEY. The module builds requests for
mocked tests; it has no network transport. YouTube post payloads are DRAFT only.
"""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
from dataclasses import dataclass, field
from pathlib import PurePath
from urllib.parse import urlencode

API_BASE = 'https://api.woopsocial.com/v1'
API_KEY_ENV = 'WOOPSOCIAL_API_KEY'


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str
    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False)

    def __repr__(self) -> str:
        return (f'PreparedRequest(method={self.method!r}, url={self.url!r}, '
                f'header_names={sorted(self.headers)!r}, body_bytes={len(self.body)})')


def _auth_headers() -> dict[str, str]:
    key = os.environ.get(API_KEY_ENV, '').strip()
    if not key:
        raise RuntimeError(f'Required environment secret {API_KEY_ENV} is missing')
    return {'Authorization': f'Bearer {key}'}


def _safe_filename(filename: str) -> str:
    # Never allow path components into a multipart header.
    name = PurePath(filename.replace('\\', '/')).name
    if not name or any(c in name for c in '\r\n"'):
        raise ValueError('Invalid upload filename')
    return name


def build_upload_request(project_id: str, filename: str, content: bytes,
                         content_type: str | None = None) -> PreparedRequest:
    """Build POST /media multipart request; does not send it."""
    if not project_id or not content:
        raise ValueError('Project and non-empty media are required')
    boundary = 'wabi-' + secrets.token_hex(16)
    name = _safe_filename(filename)
    media_type = content_type or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f'Content-Type: {media_type}\r\n\r\n'
    ).encode('utf-8') + content + f'\r\n--{boundary}--\r\n'.encode('ascii')
    headers = _auth_headers()
    headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    return PreparedRequest('POST', f'{API_BASE}/media?{urlencode({"projectId": project_id})}',
                           headers, body)


def build_youtube_draft_request(social_account_id: str, title: str, description: str,
                                media_id: str, privacy: str = 'private') -> PreparedRequest:
    """Build a DRAFT-only YouTube post request; never schedules/publishes it."""
    if not all((social_account_id, title.strip(), media_id)):
        raise ValueError('Social account, title and media ID are required')
    if privacy not in {'public', 'private', 'unlisted'}:
        raise ValueError('Unsupported YouTube privacy value')
    payload = {
        'content': [{'text': description, 'media': [{'type': 'MEDIA_LIBRARY', 'mediaId': media_id}]}],
        'schedule': {'type': 'DRAFT'},
        'socialAccounts': [{
            'platform': 'YOUTUBE',
            'socialAccountId': social_account_id,
            'title': title,
            'privacy': privacy,
        }],
    }
    headers = _auth_headers()
    headers['Content-Type'] = 'application/json'
    return PreparedRequest('POST', f'{API_BASE}/posts', headers,
                           json.dumps(payload, separators=(',', ':')).encode('utf-8'))


def run_mocked(request: PreparedRequest, transport):
    """Test-only style adapter: caller supplies its own fake transport explicitly."""
    if transport is None or not getattr(transport, 'is_test_double', False):
        raise RuntimeError('Only an explicitly marked test transport is allowed here')
    return transport(request)
