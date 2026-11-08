#!/usr/bin/env python3
"""Read-only, privacy-minimal recent-video discovery for @__eventsMT.
Only aggregate counts are printed; post IDs, text, URLs and media are never persisted or logged.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_HANDLE = '__eventsMT'
LOOKBACK_SECONDS = 3 * 60 * 60  # overlap the two-hour schedule to tolerate delayed runs
MAX_PAGES = 3


def count_page(data, handle, seen, now_epoch, lookback_seconds):
    if data.get('code') != 200 or not isinstance(data.get('results'), list):
        raise ValueError('Unexpected or incomplete source response')
    total_videos = 0
    recent_videos = 0
    for post in data['results']:
        if (post.get('author') or {}).get('screen_name', '').lower() != handle.lower():
            continue
        post_id = str(post.get('id', ''))
        if not post_id.isdigit() or post_id in seen:
            continue
        seen.add(post_id)
        try:
            created = int(post.get('created_timestamp'))
        except (TypeError, ValueError):
            created = None
        is_recent = created is not None and now_epoch - lookback_seconds <= created <= now_epoch
        for media in (post.get('media') or {}).get('all', []):
            if media.get('type') == 'video' and str(media.get('url', '')).startswith('https://video.twimg.com/'):
                total_videos += 1
                if is_recent:
                    recent_videos += 1
    return total_videos, recent_videos


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


def scan_pages(handle, now_epoch, page_loader=fetch_page):
    seen, cursors = set(), set()
    total_videos = recent_videos = pages = 0
    cursor = None
    for _ in range(MAX_PAGES):
        data = page_loader(handle, cursor)
        page_total, page_recent = count_page(data, handle, seen, now_epoch, LOOKBACK_SECONDS)
        total_videos += page_total
        recent_videos += page_recent
        pages += 1
        next_cursor = (data.get('cursor') or {}).get('bottom')
        if not data['results'] or not next_cursor:
            cursor = None
            break
        if next_cursor in cursors:
            raise ValueError('Pagination loop')
        cursors.add(next_cursor)
        cursor = next_cursor
    return {
        'pages_checked': pages,
        'videos_seen': total_videos,
        'videos_posted_within_lookback': recent_videos,
        'lookback_hours': LOOKBACK_SECONDS // 3600,
        'additional_page_available': bool(cursor),
        'candidate_audio_reviewed': False,
        'publication_performed': False,
    }


def main():
    handle = os.environ.get('SOURCE_HANDLE', DEFAULT_HANDLE).strip().lstrip('@')
    if not handle or not all(c.isascii() and (c.isalnum() or c == '_') for c in handle):
        print('Source handle is missing or invalid.', file=sys.stderr)
        return 2
    try:
        result = scan_pages(handle, int(time.time()))
    except Exception:
        print('Source check failed; results incomplete.', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
