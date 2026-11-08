#!/usr/bin/env python3
"""Read-only check, intentionally emitting only aggregate, non-identifying counts.
No posting, content download, source ledger, or persistent state."""
import json, os, sys, urllib.parse, urllib.request

def main():
    handle=os.environ.get('SOURCE_HANDLE','').strip().lstrip('@')
    if not handle or not all(c.isascii() and (c.isalnum() or c=='_') for c in handle):
        print('Source handle is missing or invalid.',file=sys.stderr); return 2
    seen=set(); cursors=set(); cursor=None; pages=0; videos=0
    try:
        for _ in range(3):
            url='https://api.fxtwitter.com/2/profile/'+urllib.parse.quote(handle,safe='')+'/media'
            params={'count':50}
            if cursor: params['cursor']=cursor
            req=urllib.request.Request(url+'?'+urllib.parse.urlencode(params), headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as response: data=json.load(response)
            if data.get('code')!=200 or not isinstance(data.get('results'),list): raise ValueError('bad response')
            pages+=1
            for p in data['results']:
                if (p.get('author') or {}).get('screen_name','').lower()!=handle.lower(): continue
                pid=str(p.get('id',''))
                if not pid.isdigit() or pid in seen: continue
                seen.add(pid)
                videos+=sum(1 for m in (p.get('media') or {}).get('all',[]) if m.get('type')=='video' and str(m.get('url','')).startswith('https://video.twimg.com/'))
            cursor=(data.get('cursor') or {}).get('bottom')
            if not data['results'] or not cursor: cursor=None;break
            if cursor in cursors: raise ValueError('pagination loop')
            cursors.add(cursor)
    except Exception:
        print('Source check failed; results incomplete.',file=sys.stderr); return 1
    print(json.dumps({'pages_checked':pages,'videos_seen':videos,'additional_page_available':bool(cursor),'candidate_audio_reviewed':False,'publication_performed':False}))
    return 0
if __name__=='__main__': sys.exit(main())
