#!/usr/bin/env python3
"""Read-only candidate listing for @__eventsMT. Never publishes or marks discovered items as posted."""
import argparse,json,sys,urllib.request,urllib.error
from pathlib import Path

URL='https://api.fxtwitter.com/2/profile/__eventsMT/media'
LEDGER=Path(__file__).with_name('published_sources.json')

def collect(data, published):
    if data.get('code') != 200 or not isinstance(data.get('results'),list):
        raise ValueError('Unexpected or incomplete source response')
    seen=set(); out=[]
    for post in data['results']:
        if (post.get('author') or {}).get('screen_name','').lower() != '__eventsmt':
            continue
        pid=str(post.get('id',''))
        if not pid.isdigit() or pid in published or pid in seen:
            continue
        seen.add(pid)
        for media in (post.get('media') or {}).get('all',[]):
            link=media.get('url','')
            if media.get('type')=='video' and link.startswith('https://video.twimg.com/'):
                out.append({'post_id':pid,'source_url':post.get('url'),'created_at':post.get('created_at'),'text':post.get('text'),'media_id':media.get('id'),'video_url':link,'duration_seconds':media.get('duration'),'music_checked':False,'published':False})
    return out

def main(argv=None):
    ap=argparse.ArgumentParser(description='Read-only eventsMT candidate discovery')
    ap.add_argument('--snapshot',help='Use a saved first-page JSON instead of fetching')
    ap.add_argument('--max-pages',type=int,default=3)
    ap.add_argument('--count',type=int,default=50)
    args=ap.parse_args(argv)
    if not 1 <= args.max_pages <= 20 or not 1 <= args.count <= 100:
        ap.error('max-pages must be 1–20; count must be 1–100')
    try:
        if args.snapshot:
            ledger=json.loads(LEDGER.read_text(encoding='utf-8'))
            published=set(str(x) for x in ledger['published_source_ids'])
            data=json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
            result={'source':URL,'published_excluded':sorted(published),
                    'candidates':collect(data,published),'errors':[],
                    'note':'Snapshot covers one saved source page only; music is unchecked.'}
        else:
            # Imported only for a live scan: paginated_candidates reuses collect/LEDGER above.
            from paginated_candidates import run
            result=run(args.max_pages,args.count)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result.get('errors') else 0
    except Exception as exc:
        print(f'Could not inspect source: {exc}',file=sys.stderr)
        return 1
if __name__=='__main__': sys.exit(main())
