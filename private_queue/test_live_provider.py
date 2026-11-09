#!/usr/bin/env python3
"""One-shot, nonpublishing live adapter test. Checkpoints go to encrypted queue.

Each state is committed by workflow before its next external mutation. A pending
state is never retried automatically. No actual source videos are used.
"""
import hashlib,json,subprocess,sys,tempfile,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent));sys.path.insert(0,str(ROOT))
from secure_scan import read_key,load_snapshot,write_encrypted
from woopsocial_adapter import Provider

TAG='wabi_integration_test_20261109'

def init(s,p):
    if 'integration_test' in s: raise ValueError('test receipt exists; reconcile first')
    matches=[]
    for project in p.projects():
        accounts=p.call('GET','/social-accounts?'+urllib.parse.urlencode({'projectId':project['id']}))
        for account in accounts:
            if account.get('platform')=='YOUTUBE' and account.get('status')=='CONNECTED': matches.append((project['id'],account['id']))
    if len(matches)!=1: raise ValueError('expected exactly one connected YouTube project')
    project,account=matches[0]
    s['integration_test']={'tag':TAG,'state':'upload_pending','project':project,'account':account}
    return s

def upload(s,p,data):
    t=s['integration_test']
    if t['state']!='upload_pending': raise ValueError('upload state invalid')
    media=p.upload(t['project'],data)
    t.update(state='uploaded',media_id=media,sha256=hashlib.sha256(data).hexdigest())
    return s

def prepare_draft(s,p):
    t=s['integration_test']
    if t['state']!='uploaded': raise ValueError('not uploaded')
    found=p.call('GET','/media?'+urllib.parse.urlencode({'projectId':t['project'],'mediaId':t['media_id']}))
    if not any(m.get('id')==t['media_id'] and m.get('projectId')==t['project'] for m in found.get('media',[])):
        raise ValueError('uploaded media not found')
    t['state']='draft_pending';return s

def draft(s,p):
    t=s['integration_test']
    if t['state']!='draft_pending': raise ValueError('draft state invalid')
    post=p.draft(t['account'],'Wabi integration test - draft only',TAG,t['media_id'])
    t.update(state='draft_created',post_id=post)
    return s

def verify(s,p):
    t=s['integration_test']
    if t['state']!='draft_created': raise ValueError('draft not yet recorded')
    post=p.post(t['post_id'])
    if post.get('id')!=t['post_id'] or post.get('schedule',{}).get('type')!='DRAFT': raise ValueError('draft not confirmed')
    if post.get('projectId')!=t['project']: raise ValueError('unexpected project')
    if not any(x.get('socialAccountId')==t['account'] and x.get('deliveryStatus')=='NOT_STARTED' for x in post.get('socialAccountPosts',[])):
        raise ValueError('draft target/status not confirmed')
    t['state']='verified_draft';return s

def main():
    phase=sys.argv[1];f=read_key();s=load_snapshot(f);p=Provider()
    if phase=='init': init(s,p)
    elif phase=='upload':
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=320x568:r=24:d=2','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart','-y',str(path)],check=True,timeout=45)
            upload(s,p,path.read_bytes())
    elif phase=='prepare_draft':prepare_draft(s,p)
    elif phase=='draft':draft(s,p)
    elif phase=='verify':verify(s,p)
    else:raise ValueError('invalid phase')
    write_encrypted(f,s);print('Integration test checkpoint:',s['integration_test']['state'])

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Test stopped safely:',type(e).__name__,str(e)[:100],file=sys.stderr);sys.exit(1)
