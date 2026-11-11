#!/usr/bin/env python3
"""Conditional compilation rendering/delivery. No classifier can clear audio.
Only an exact signed source review can authorize audio-preserving transcoding.
All provider writes have durable pre-write checkpoints; unknown writes are never retried.
"""
import hashlib, json, math, os, re, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
from compilation_assessment import assess, probe_bytes
from audio_review import verifier
from candidate_pipeline import _key
from compilation_sources import candidates
from secure_scan import read_key,load_snapshot
from prepare_media import get_media
from git_checkpoint import encrypted_git_checkpoint
from zernio_adapter import ZernioProvider,stable_idempotency_key

MIN=600.0

def sha(data): return hashlib.sha256(data).hexdigest()
def run(args):
    return subprocess.run(args,check=True,capture_output=True,timeout=1200)

def choose_plan(rows):
    """Full, unique source clips only. Never loop footage to reach ten minutes."""
    out=[]; total=0
    for row in rows:
        d=float(row['duration_seconds'])
        if not math.isfinite(d) or d<=0: raise ValueError('invalid duration')
        out.append(row);total+=d
        if total>=MIN: return out
    return []

def unused_rows(snapshot, rows):
    records=snapshot.get('compilation_attempts',{}).values()
    used_sources={k.split(':')[0] for r in records if r.get('state')=='published' for k in r['source_keys']}
    used_hashes={h for r in snapshot.get('compilation_attempts',{}).values() if r.get('state')=='published' for h in r['source_sha256']}
    return [r for r in rows if r['key'].split(':')[0] not in used_sources and r['sha256'] not in used_hashes]

def metadata(items):
    texts=[]
    for item in items:
        text=' '.join(re.sub(r'https?://\S+|[\x00-\x1f]',' ',str(item.get('text') or '')).split())
        text=re.sub(r'[@#]\S+','',text).strip(' -|')
        if text and text not in texts: texts.append(text)
    # An extract of actual source descriptions, not invented event claims.
    anchor=(texts[0][:48].strip() if texts else 'أحداث MT')
    title=('تجميع أحداث MT | '+anchor)[:100]
    description='تجميع من أحداث MT، بالصوت الأصلي دون إضافة موسيقى.\n\n'
    description+='\n'.join('المصدر: https://x.com/__eventsMT/status/'+str(i['post_id']) for i in items)
    return title,description[:4900],anchor

def thumbnail(frames,dest,anchor):
    from PIL import Image,ImageOps,ImageDraw,ImageFont
    canvas=Image.new('RGB',(1280,720),'#0b1220')
    for index,path in enumerate(frames):
        im=ImageOps.fit(Image.open(path).convert('RGB'),(640,480))
        canvas.paste(im,(index*640,0))
    draw=ImageDraw.Draw(canvas)
    draw.rectangle((0,468,1280,720),fill='#111c30')
    draw.rectangle((0,468,1280,480),fill='#e8ae48')
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    draw.text((44,500),'MT • ZICO',font=ImageFont.truetype(font,46),fill='#e8ae48')
    # Pillow with libraqm handles Arabic shaping; fail instead of broken lettering.
    from PIL import features
    if not features.check('raqm'): raise RuntimeError('Arabic shaping unavailable')
    label=anchor[:40]
    draw.text((1235,587),label,font=ImageFont.truetype(font,42),fill='white',anchor='ra',direction='rtl')
    canvas.save(dest,format='JPEG',quality=88)
    if Path(dest).stat().st_size>2_000_000: raise ValueError('thumbnail too large')

def render(snapshot,plan,verify,output,thumb,fetch=get_media):
    if not plan or sum(r['duration_seconds'] for r in plan)<MIN: raise ValueError('insufficient duration')
    items_by_key={_key(i):i for i in candidates(snapshot)}
    if len({r['key'].split(':')[0] for r in plan})!=len(plan) or len({r['sha256'] for r in plan})!=len(plan):
        raise ValueError('duplicate source or media')
    items=[]
    with tempfile.TemporaryDirectory(prefix='compile-sources-') as directory:
        base=Path(directory);os.chmod(base,0o700);parts=[];frames=[]
        for n,row in enumerate(plan):
            item=items_by_key[row['key']];data=fetch(item['video_url'])
            if sha(data)!=row['sha256'] or snapshot.get('prepared_media',{}).get(row['key'],{}).get('sha256')!=sha(data):
                raise ValueError('source changed')
            if not verify(item,data,snapshot.get('audio_reviews',{}).get(row['key'])): raise ValueError('source not cleared')
            duration=probe_bytes(data)
            if abs(duration-row['duration_seconds'])>.1: raise ValueError('duration changed')
            src=base/f'{n}.mp4';src.write_bytes(data);os.chmod(src,0o600)
            dest=base/f'{n}-normalized.mp4'
            run(['ffmpeg','-nostdin','-v','error','-i',str(src),'-map','0:v:0','-map','0:a:0','-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25','-c:v','libx264','-threads','2','-preset','veryfast','-crf','23','-c:a','aac','-ar','48000','-ac','2',str(dest)])
            parts.append(dest);items.append(item)
            if len(frames)<2:
                image=base/f'frame-{n}.jpg'
                run(['ffmpeg','-nostdin','-v','error','-ss',str(min(2,duration/2)),'-i',str(src),'-frames:v','1','-q:v','2',str(image)])
                frames.append(image)
        if len(frames)==1: frames.append(frames[0])
        listing=base/'concat.txt';listing.write_text(''.join("file '"+str(p)+"'\n" for p in parts))
        run(['ffmpeg','-nostdin','-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(output)])
        final_duration=probe_bytes(Path(output).read_bytes())
        if not math.isfinite(final_duration) or final_duration<MIN: raise ValueError('rendered duration invalid')
        if abs(final_duration-sum(r['duration_seconds'] for r in plan))>len(plan)*.15+1: raise ValueError('rendered duration mismatch')
        title,description,anchor=metadata(items)
        thumbnail(frames,thumb,anchor)
        return {'title':title,'description':description,'duration_seconds':final_duration,'video_sha256':sha(Path(output).read_bytes()),'thumbnail_sha256':sha(Path(thumb).read_bytes())}

class Delivery:
    def __init__(self,snapshot,checkpoint,provider):
        self.s=snapshot;self.cp=checkpoint;self.p=provider;self.poisoned=False
    def save(self):
        if self.poisoned: raise ValueError('reload durable state')
        try:self.cp(self.s)
        except Exception:
            self.poisoned=True;raise
    def reconcile(self):
        for record in self.s.get('compilation_attempts',{}).values():
            if record.get('state') not in {'delivery_recorded','delivery_scheduled'}:continue
            post=self.p.post(record['post_id'])
            if post.get('id')!=record['post_id'] or post.get('projectId')!=record['project']:raise ValueError('post identity mismatch')
            rows=[r for r in post.get('socialAccountPosts',[]) if r.get('platform')=='youtube' and r.get('socialAccountId')==record['account']]
            if len(rows)!=1:raise ValueError('destination mismatch')
            row=rows[0];status=row.get('deliveryStatus')
            if status=='PUBLISHED':
                record.update(state='published',published_at=datetime.now(timezone.utc).isoformat(),external_post_url=row.get('externalPostUrl'))
                self.save()
            elif status=='FAILED':record['state']='failed_confirmed';self.save()
            elif status=='SCHEDULED' and record['state']!='delivery_scheduled':record['state']='delivery_scheduled';self.save()
    def submit(self,plan,details,video,image):
        if self.poisoned:raise ValueError('reload durable state')
        if not math.isfinite(details['duration_seconds']) or details['duration_seconds']<MIN or not plan or sum(r['duration_seconds'] for r in plan)<MIN:
            raise ValueError('insufficient duration')
        if len({r['key'].split(':')[0] for r in plan})!=len(plan) or len({r['sha256'] for r in plan})!=len(plan):
            raise ValueError('duplicate source or media')
        if sha(video)!=details['video_sha256'] or sha(image)!=details['thumbnail_sha256']:raise ValueError('rendered bytes changed')
        ledger=self.s.setdefault('compilation_attempts',{})
        unresolved=[r for r in ledger.values() if r.get('state') not in {'published','failed_confirmed','abandoned_before_upload'}]
        if unresolved:raise ValueError('unresolved compilation attempt')
        # Enforce 24-hour cadence without inventing a recurring user time.
        now=datetime.now(timezone.utc)
        for r in ledger.values():
            if r.get('state')=='published' and now-datetime.fromisoformat(r['published_at'])<timedelta(hours=24):return 'cadence_wait'
        used_sources={k.split(':')[0] for r in ledger.values() if r.get('state')=='published' for k in r['source_keys']}
        used_hashes={h for r in ledger.values() if r.get('state')=='published' for h in r['source_sha256']}
        if any(r['key'].split(':')[0] in used_sources or r['sha256'] in used_hashes for r in plan):raise ValueError('source already compiled')
        if not self.p.verify_destination(self.p.profile,self.p.account):raise ValueError('destination unavailable')
        key=stable_idempotency_key(self.p.account,'compilation',details['video_sha256'])
        if key in ledger:raise ValueError('attempt already exists')
        record={'state':'upload_uncertain','source_keys':[r['key'] for r in plan],'source_sha256':[r['sha256'] for r in plan],**details,'project':self.p.profile,'account':self.p.account,'provider':'zernio','created_at':now.isoformat(),'idempotency_key':key}
        ledger[key]=record;self.save()
        url=self.p.upload(self.p.profile,video,filename='eventsmt-compilation.mp4')
        if not self.p.verify_media(self.p.profile,url):raise ValueError('media unavailable')
        record.update(media_url=url);self.save()
        # Thumbnail upload is independently uncertain. Never automatically retry either upload.
        image_url=self.p.upload_image(self.p.profile,image)
        record.update(thumbnail_url=image_url,state='upload_complete');self.save()
        scheduled=(now+timedelta(minutes=15)).isoformat()
        record.update(state='delivery_uncertain',scheduled_for=scheduled);self.save()
        post_id=self.p.publish_compilation(self.p.account,details['title'],details['description'],url,image_url,scheduled,key)
        if not isinstance(post_id,str) or not post_id:raise ValueError('submission unknown')
        record.update(state='delivery_recorded',post_id=post_id);self.save()
        self.reconcile()
        return record['state']

def main():
    if os.environ.get('COMPILATION_ENABLED')!='true':
        print('Compilation not enabled.');return
    f=read_key();snapshot=load_snapshot(f)
    provider=ZernioProvider();cp=lambda s:encrypted_git_checkpoint(HERE.parent,f,s)
    delivery=Delivery(snapshot,cp,provider);delivery.reconcile()
    verify=verifier(os.environ.get('AUDIO_REVIEW_PUBLIC_KEY',''))
    summary,rows=assess(snapshot,verify,return_plan=True)
    print(json.dumps(summary,sort_keys=True),flush=True)
    if not summary['eligible_for_preparation']:return
    plan=choose_plan(unused_rows(snapshot,rows))
    if not plan:
        print('No ten-minute batch of unique cleared source clips.');return
    with tempfile.TemporaryDirectory(prefix='eventsmt-final-') as d:
        os.chmod(d,0o700);video=Path(d)/'compilation.mp4';image=Path(d)/'thumbnail.jpg'
        details=render(snapshot,plan,verify,video,image)
        state=delivery.submit(plan,details,video.read_bytes(),image.read_bytes())
        print('Compilation delivery state: '+state)
if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Media, source text, URLs and credentials must stay out of public logs.
        print('Compilation stopped safely: '+type(exc).__name__,file=sys.stderr);raise SystemExit(1)
