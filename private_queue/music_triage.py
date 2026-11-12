#!/usr/bin/env python3
"""CPU audio music risk triage, not a song-free decision or publication approval.

Processes at most one prepared unreviewed candidate per invocation; exact-byte
SHA verification is required. Scores and fingerprint are stored encrypted; never
print source identity, URL or audio. No mutation of signed reviews or deliveries.
"""
import hashlib, json, math, os, subprocess, sys, tempfile
from pathlib import Path
from candidate_pipeline import _key
from candidate_recency import newest_first

MODEL_VERSION='yamnet-efficientat-20261111-v2-wholetrack'
Y_SHA='d3835ffbbd4a1bb3e777f0ca217b5007907f5171dd5d17c4236b95b2af8f908e'
E_SHA='f11d0be24823294117798e3c385f53c8193e61e68637fcdd78df32313c4463bd'
THRESHOLD=0.10
MAX_DURATION=240.0  # Whole audio is still required; longer media stays blocked.

def model_path(path,digest):
    p=Path(path)
    if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: raise ValueError('model hash mismatch')
    return p

def select(s, excluded=None):
    excluded = excluded or set()
    prepared=s.get('prepared_media',{}); prior=s.get('music_triage',{}); reviewed=s.get('audio_reviews',{})
    published=set(map(str,s['ledger']['published_source_ids']))
    for item in newest_first(s['state']['pending']):
        key=_key(item); prep=prepared.get(key,{})
        if key in excluded: continue
        if key.split(':')[0] in published or key in reviewed or prep.get('has_audio') is not True: continue
        old=prior.get(key,{})
        if old.get('sha256')==prep.get('sha256') and old.get('model_version')==MODEL_VERSION: continue
        return item
    return None

def calculate(wave,y,e,np):
    if len(wave)<1 or not np.all(np.isfinite(wave)): raise ValueError('empty or corrupt audio')
    ym=em=0.0
    for start in range(0,len(wave),80000):
        a=wave[start:start+80000]
        if len(a)<15600: a=np.pad(a,(0,15600-len(a)))
        yy=y.run(None,{'waveform':a})[0]
        if len(a)<80000: a=np.pad(a,(0,80000-len(a)))
        xx=np.interp(np.arange(160000)/2,np.arange(80000),a).astype('float32')
        ee=np.asarray(e.run(None,{'wave':xx[None,:]})[0]).reshape(-1)
        ym=max(ym,float(yy[:,132].max())); em=max(em,float(ee[137]))
    if not all(math.isfinite(x) and 0<=x<=1 for x in (ym,em)): raise ValueError('invalid model score')
    return ym,em

def score(data, model_dir):
    # Dependencies imported lazily so standard workflow unit tests need no ML packages.
    import numpy as np, onnxruntime as ort
    Y=model_path(Path(model_dir)/'yamnet.onnx',Y_SHA); E=model_path(Path(model_dir)/'mn10_as.onnx',E_SHA)
    opt=ort.SessionOptions();opt.intra_op_num_threads=1;opt.inter_op_num_threads=1;opt.log_severity_level=3
    y=ort.InferenceSession(str(Y),sess_options=opt,providers=['CPUExecutionProvider'])
    e=ort.InferenceSession(str(E),sess_options=opt,providers=['CPUExecutionProvider'])
    with tempfile.TemporaryDirectory(prefix='music-triage-') as d:
        os.chmod(d,0o700);p=Path(d)/'video.mp4';p.write_bytes(data);os.chmod(p,0o600)
        r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(p)],capture_output=True,check=True,timeout=30)
        details=json.loads(r.stdout);duration=float(details['format']['duration']);types={s.get('codec_type') for s in details.get('streams',[])}
        if not math.isfinite(duration) or not (0<duration<=MAX_DURATION) or 'audio' not in types or 'video' not in types: raise ValueError('invalid input duration or streams')
        r=subprocess.run(['ffmpeg','-v','error','-i',str(p),'-vn','-ac','1','-ar','16000','-f','f32le','-acodec','pcm_f32le','-'],capture_output=True,check=True,timeout=90)
        wave=np.frombuffer(r.stdout,dtype='<f4')
        actual=len(wave)/16000
        if not (0<actual<=MAX_DURATION+1) or actual < max(.5,duration-3): raise ValueError('incomplete audio decoding')
        ym,em=calculate(wave,y,e,np)
    return {'duration_seconds':round(actual,3),'yamnet_peak':round(ym,6),'efficientat_peak':round(em,6),
            'assessment_scope':'entire_audio',
            'classification':'music_suspected' if max(ym,em)>=0.05 else 'low_risk'}

def triage_one(s,fetch=None,scorer=None,excluded=None):
    if fetch is None:
        from prepare_media import get_media
        fetch=get_media
    item=select(s,excluded)
    if item is None:return False
    key=_key(item);data=fetch(item['video_url']);digest=hashlib.sha256(data).hexdigest()
    if digest!=s['prepared_media'][key].get('sha256'):raise ValueError('prepared bytes changed')
    if scorer is None:scorer=lambda data:score(data,os.environ['MUSIC_MODEL_DIR'])
    result=scorer(data)
    if result.get('classification') not in {'music_suspected','inconclusive','low_risk'}:raise ValueError('bad result')
    s.setdefault('music_triage',{})[key]={**result,'sha256':digest,'model_version':MODEL_VERSION,'is_clearance':False}
    return True

def triage_batch(s, save, fetch=None, scorer=None, limit=12):
    # A single unreadable or changed clip must not starve other clips. No score
    # means no clearance; only successful exact-byte assessments are saved.
    excluded=set(); saved=failed=0
    for _ in range(limit):
        item=select(s,excluded)
        if item is None: break
        key=_key(item)
        try:
            changed=triage_one(s,fetch,scorer,excluded)
        except Exception:
            excluded.add(key); failed+=1
            continue
        if changed:
            save(s); saved+=1
    return saved,failed

def main():
    from secure_scan import read_key, load_snapshot, write_encrypted
    f=read_key();s=load_snapshot(f)
    saved,failed=triage_batch(s,lambda obj:write_encrypted(f,obj))
    print('Probabilistic whole-track assessments saved:',saved,'; failed or unreadable:',failed,'; not human reviews.')
    if failed: raise ValueError('one or more assessments failed closed')
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Music assessment stopped safely: '+type(exc).__name__,file=sys.stderr);raise SystemExit(1)
