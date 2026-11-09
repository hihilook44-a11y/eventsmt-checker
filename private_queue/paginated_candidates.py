#!/usr/bin/env python3
"""Read-only paginated @__eventsMT media discovery. No upload, publication or ledger writes.

First pages may be incomplete; bounded scans always report remaining cursor and failures.
Video candidates are unreviewed; a classifier score does not clear music.
"""
import argparse, json, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from candidates import URL, LEDGER, collect


def run(max_pages=3, count=50, endpoint="media"):
    if endpoint not in ("media", "statuses"): raise ValueError("invalid discovery endpoint")
    source_url = URL if endpoint == "media" else URL.rsplit("/", 1)[0] + "/statuses"
    ledger=json.loads(LEDGER.read_text(encoding='utf-8'))
    published=set(str(x) for x in ledger['published_source_ids'])
    pages=[]; candidates=[]; seen=set(); seen_cursors=set(); cursor=None; errors=[]; ended=False
    for page_number in range(1, max_pages+1):
        params={'count':count}
        if cursor: params['cursor']=cursor
        url=source_url+'?'+urllib.parse.urlencode(params)
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=25) as resp: data=json.load(resp)
            found=collect(data,published)
            posts=data['results']
            for v in found:
                identity=(v['post_id'],str(v.get('media_id')),v['video_url'])
                if identity not in seen:
                    candidates.append(v);seen.add(identity)
            bottom=(data.get('cursor') or {}).get('bottom')
            pages.append({'page':page_number,'posts':len(posts),'candidates_before_dedup':len(found),
                'timestamps':[p.get('created_timestamp') for p in posts if isinstance(p,dict) and (p.get('author') or {}).get('screen_name','').lower() == '__eventsmt' and isinstance(p.get('created_timestamp'),(int,float)) and not isinstance(p.get('created_timestamp'),bool)],
                'has_next':bool(bottom)})
            if not posts or not bottom: ended=True;cursor=None;break
            if bottom in seen_cursors:
                errors.append('Repeated pagination cursor; stopped to avoid a loop');cursor=bottom;break
            seen_cursors.add(bottom);cursor=bottom
        except Exception as exc:
            errors.append(f'Page {page_number}: {type(exc).__name__}: {exc}');break
    return {'source':source_url,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'published_excluded':sorted(published),'pages':pages,'candidates':candidates,
        'end_of_timeline_seen':ended,'next_cursor_available':bool(cursor),
        'errors':errors,'note':'Bounded read-only scan; pagination/timestamps are not a completeness guarantee. Music is unchecked and no publication is authorized by these results.'}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--max-pages',type=int,default=3);ap.add_argument('--count',type=int,default=50);ap.add_argument('--output')
    a=ap.parse_args()
    if not 1<=a.max_pages<=20 or not 1<=a.count<=100: ap.error('max-pages must be 1–20; count must be 1–100')
    try: result=run(a.max_pages,a.count)
    except Exception as e: print(f'Cannot inspect source/ledger: {e}',file=sys.stderr);sys.exit(1)
    body=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output: Path(a.output).write_text(body+'\n',encoding='utf-8')
    print(body)
    if result['errors']:sys.exit(2)
