#!/usr/bin/env python3
"""Download one queued source into an ephemeral working directory for review.

No submission, audio-clearance inference, publication, or durable plaintext media.
Only media fingerprint and probe metadata are stored inside the encrypted snapshot.
"""
import hashlib,json,os,signal,subprocess,sys,tempfile,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from secure_scan import read_key,load_snapshot,write_encrypted
from woopsocial_adapter import Queue

MAX_BYTES=100_000_000
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def check_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='video.twimg.com' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('unexpected media origin')
    return url

def eligible(snapshot):
    ledger=set(map(str,snapshot['ledger']['published_source_ids']))
    already=snapshot.get('prepared_media',{})
    for item in snapshot['state']['pending']:
        source=str(item.get('post_id','')); media=str(item.get('media_id',''))
        if source.isdigit() and media.isdigit() and source not in ledger and source+':'+media not in already:
            return item
    return None

def get_media(url,opener=None):
    check_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    opener=opener or urllib.request.build_opener(SafeRedirect())
    # Per-socket timeouts do not bound a slow streaming response. Impose a
    # whole-transfer limit so preparation cannot hold the publication job forever.
    def deadline(_signum, _frame):
        raise TimeoutError('media download exceeded total deadline')
    old_handler=signal.signal(signal.SIGALRM,deadline)
    signal.alarm(90)
    try:
        with opener.open(req,timeout=40) as r:
            check_url(r.geturl())
            data=r.read(MAX_BYTES+1)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM,old_handler)
    if not data or len(data)>MAX_BYTES: raise ValueError('invalid media size')
    return data

def prepare(snapshot,fetch=get_media,probe=None):
    item=eligible(snapshot)
    if item is None: return False
    data=fetch(item['video_url'])
    with tempfile.TemporaryDirectory(prefix='private-media-') as d:
        os.chmod(d,0o700)
        media=Path(d)/'source.mp4';media.write_bytes(data);os.chmod(media,0o600)
        if probe is None:
            raw=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(media)],capture_output=True,check=True,timeout=45)
            detail=json.loads(raw.stdout)
        else: detail=probe(media)
        duration=float(detail['format']['duration'])
        if duration<=0 or not any(x.get('codec_type')=='video' for x in detail.get('streams',[])): raise ValueError('invalid video')
        q=Queue(Path(d)/'review.sqlite')
        q.register(str(item['post_id']),data,set(map(str,snapshot['ledger']['published_source_ids'])))
        if q.pending()[0][1]!='awaiting_review': raise ValueError('review gate failed')
        q.db.close()
    key=str(item['post_id'])+':'+str(item['media_id'])
    snapshot.setdefault('prepared_media',{})[key]={'sha256':hashlib.sha256(data).hexdigest(),'duration_seconds':duration,'has_audio':any(s.get('codec_type')=='audio' for s in detail['streams']),'status':'awaiting_audio_review'}
    return True

def main():
    f=read_key(); snapshot=load_snapshot(f)
    if prepare(snapshot): write_encrypted(f,snapshot);print('One candidate prepared for audio review; no upload or publication.')
    else: print('No unprepared candidate in queue; no upload or publication.')
if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Preparation failed safely: '+type(exc).__name__,file=sys.stderr);raise SystemExit(1)
