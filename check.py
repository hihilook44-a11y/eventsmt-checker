#!/usr/bin/env python3
"""Read-only discovery plus a public hashed-ID durable seen ledger.

Never logs post IDs, text, URLs, or media. Audio review/publication are not performed.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_HANDLE = '__eventsMT'
MAX_PAGES = 3
MAX_LEDGER_IDS = 5000
STATE_PATH = Path(os.environ.get('STATE_PATH', 'state/seen_post_ids.json'))


def fetch_page(handle, cursor=None):
    url = 'https://api.fxtwitter.com/2/profile/' + urllib.parse.quote(handle, safe='') + '/media'
    params = {'count': 50}
    if cursor:
        params['cursor'] = cursor
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers={
        'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def id_digest(post_id):
    return hashlib.sha256(post_id.encode('ascii')).hexdigest()


def load_state(path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('Saved state is unreadable') from exc
    if (not isinstance(value, dict) or value.get('schema') != 1
            or not isinstance(value.get('id_sha256'), list)
            or not isinstance(value.get('last_successful_scan'), int)
            or any(not isinstance(i, str) or len(i) != 64
                   or any(c not in '0123456789abcdef' for c in i)
                   for i in value['id_sha256'])):
        raise ValueError('Saved state is invalid')
    return value


def collect_pages(handle, page_loader=fetch_page):
    posts, seen, cursors = [], set(), set()
    cursor = None
    pages = 0
    for _ in range(MAX_PAGES):
        data = page_loader(handle, cursor)
        if data.get('code') != 200 or not isinstance(data.get('results'), list):
            raise ValueError('Unexpected or incomplete source response')
        pages += 1
        for post in data['results']:
            if (post.get('author') or {}).get('screen_name', '').lower() != handle.lower():
                continue
            pid = str(post.get('id', ''))
            if pid.isdigit() and pid not in seen:
                seen.add(pid)
                posts.append(post)
        next_cursor = (data.get('cursor') or {}).get('bottom')
        if not data['results'] or not next_cursor:
            cursor = None
            break
        if next_cursor in cursors:
            raise ValueError('Pagination loop')
        cursors.add(next_cursor)
        cursor = next_cursor
    additional_page_available = pages == MAX_PAGES and bool(cursor)
    return posts, pages, additional_page_available


def video_posts(posts):
    result = []
    for post in posts:
        media = (post.get('media') or {}).get('all', [])
        videos = [m for m in media if m.get('type') == 'video'
                  and str(m.get('url', '')).startswith('https://video.twimg.com/')]
        if videos:
            try:
                created = int(post.get('created_timestamp'))
            except (TypeError, ValueError):
                created = None
            result.append((str(post['id']), created))
    return result


def save_state(path, digests, scanned_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'schema': 1, 'last_successful_scan': scanned_at,
               'id_sha256': sorted(digests)[-MAX_LEDGER_IDS:]}
    fd, temp = tempfile.mkstemp(prefix='.seen-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, separators=(',', ':'))
            f.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def scan(handle, now_epoch, page_loader=fetch_page, state_path=STATE_PATH):
    state = load_state(state_path)
    posts, pages, more = collect_pages(handle, page_loader)
    vids = video_posts(posts)
    old_digests = set(state['id_sha256']) if state else set()
    last_scan = state['last_successful_scan'] if state else None
    # First successful run is a baseline: do not treat existing history as newly arrived.
    new_count = 0 if last_scan is None else sum(
        1 for pid, created in vids
        if id_digest(pid) not in old_digests and created is not None and created > last_scan
    )
    digests = old_digests | {id_digest(pid) for pid, _ in vids}
    save_state(state_path, digests, now_epoch)
    return {
        'pages_checked': pages,
        'video_posts_seen': len(vids),
        'new_video_posts_since_last_successful_scan': new_count,
        'baseline_created': state is None,
        'additional_page_available': more,
        'candidate_audio_reviewed': False,
        'publication_performed': False,
    }


def main():
    handle = os.environ.get('SOURCE_HANDLE', DEFAULT_HANDLE).strip().lstrip('@')
    if not handle or not all(c.isascii() and (c.isalnum() or c == '_') for c in handle):
        print('Source handle is missing or invalid.', file=sys.stderr)
        return 2
    try:
        result = scan(handle, int(time.time()))
    except Exception:
        print('Source check failed; results incomplete; saved state was not advanced.', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
