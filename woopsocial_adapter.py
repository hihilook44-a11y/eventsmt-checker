#!/usr/bin/env python3
"""Real WoopSocial transport and fail-closed private draft queue.
No scheduler or automatic song detection. Public submission requires a verified review gate.
"""
import hashlib,json,os,sqlite3,urllib.request,urllib.parse,urllib.error,uuid
from pathlib import Path

BASE='https://api.woopsocial.com/v1'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
class ProviderError(Exception): pass
class Provider:
    name = 'woopsocial'
    def __init__(self,key=None,opener=None):
        self.key=(key or os.environ.get('WOOPSOCIAL_API_KEY','')).strip()
        if not self.key: raise ValueError('WOOPSOCIAL_API_KEY missing')
        self.opener=opener or urllib.request.build_opener(NoRedirect())
    def call(self,method,path,body=None,content_type=None):
        if not path.startswith('/') or path.startswith('//') or '\r' in path or '\n' in path: raise ValueError('invalid path')
        headers={'Authorization':'Bearer '+self.key,'Accept':'application/json'}
        if content_type: headers['Content-Type']=content_type
        req=urllib.request.Request(BASE+path,data=body,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=45) as r:
                if r.status not in (200,201): raise ProviderError('unexpected HTTP status')
                return json.loads(r.read())
        except urllib.error.HTTPError as e: raise ProviderError('HTTP '+str(e.code)) from None
        except (urllib.error.URLError,TimeoutError,ValueError,OSError) as e: raise ProviderError('transport or response error: '+type(e).__name__) from None
    def projects(self): return self.call('GET','/projects')
    def accounts(self): return self.call('GET','/social-accounts')
    def post(self,post_id): return self.call('GET','/posts/'+urllib.parse.quote(post_id,safe=''))
    def validate(self,payload): return self.call('POST','/posts/validate',json.dumps(payload,ensure_ascii=False).encode(),'application/json')
    def upload(self,project,content,filename='clip.mp4'):
        if not content or len(content)>100_000_000: raise ValueError('media empty or over 100MB')
        boundary='wabi'+uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()+content+f'\r\n--{boundary}--\r\n'.encode())
        result=self.call('POST','/media?'+urllib.parse.urlencode({'projectId':project}),body,'multipart/form-data; boundary='+boundary)
        if not isinstance(result,dict) or not result.get('mediaId'): raise ProviderError('upload response lacks mediaId')
        return result['mediaId']
    def publish_now(self,account,title,description,media):
        """Submit a public YouTube post. Caller owns durable idempotency and review."""
        if not all((account,title,media)): raise ValueError('missing post fields')
        payload={'content':[{'text':description,'media':[{'type':'MEDIA_LIBRARY','mediaId':media}]}], 'schedule':{'type':'PUBLISH_NOW'},'socialAccounts':[{'platform':'YOUTUBE','socialAccountId':account,'title':title,'privacy':'public'}]}
        result=self.call('POST','/posts',json.dumps(payload,ensure_ascii=False).encode(),'application/json')
        if not isinstance(result,dict) or not result.get('id') or result.get('schedule',{}).get('type')!='PUBLISH_NOW': raise ProviderError('publication response uncertain')
        return result['id']
    def draft(self,account,title,description,media):
        if not all((account,title,media)): raise ValueError('missing post fields')
        payload={'content':[{'text':description,'media':[{'type':'MEDIA_LIBRARY','mediaId':media}]}], 'schedule':{'type':'DRAFT'},'socialAccounts':[{'platform':'YOUTUBE','socialAccountId':account,'title':title,'privacy':'private'}]}
        result=self.call('POST','/posts',json.dumps(payload,ensure_ascii=False).encode(),'application/json')
        if not isinstance(result,dict) or not result.get('id') or result.get('schedule',{}).get('type')!='DRAFT': raise ProviderError('draft response uncertain')
        return result['id']

def digest(data): return hashlib.sha256(data).hexdigest()
class Queue:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=20,isolation_level=None)
        if str(path)!=':memory:': os.chmod(path,0o600)
        self.db.execute('pragma journal_mode=WAL'); self.db.execute('pragma synchronous=FULL')
        self.db.execute('create table if not exists items (source text primary key, digest text not null, state text not null, media_id text, post_id text)')
    def register(self,source,data,published):
        if not source.isdigit() or not data: raise ValueError('invalid source/media')
        if source in published: raise ValueError('already published')
        old=self.db.execute('select digest from items where source=?',(source,)).fetchone()
        if old and old[0]!=digest(data): raise ValueError('media changed')
        self.db.execute('insert or ignore into items(source,digest,state) values(?,?,?)',(source,digest(data),'awaiting_review'))
    def pending(self): return self.db.execute('select source,state,media_id,post_id from items order by source').fetchall()
    def _transition(self,source,before,after,**fields):
        allowed={'media_id','post_id'}
        if set(fields)-allowed: raise ValueError('invalid field')
        names=list(fields); sql='update items set state=?'+''.join(','+n+'=?' for n in names)+' where source=? and state=?'
        if self.db.execute(sql,[after]+[fields[n] for n in names]+[source,before]).rowcount!=1: raise ValueError('invalid state')
    def create_draft(self,source,data,project,account,title,description,provider):
        """Requires an independently implemented, authenticated review gate.
        No route currently promotes awaiting_review to ready: fail closed.
        """
        row=self.db.execute('select digest,state,media_id from items where source=?',(source,)).fetchone()
        if not row or row[0]!=digest(data) or row[1]!='ready': raise ValueError('no authenticated full-audio review')
        self._transition(source,'ready','upload_uncertain')
        media=provider.upload(project,data)
        self._transition(source,'upload_uncertain','upload_complete',media_id=media)
        self._transition(source,'upload_complete','draft_uncertain')
        post=provider.draft(account,title,description,media)
        self._transition(source,'draft_uncertain','draft_created',post_id=post)
        return post

def import_candidates(queue,source_file,ledger_file,clips_dir):
    """Read existing queue and exclude already published; do not change either."""
    source=json.loads(Path(source_file).read_text()); ledger=json.loads(Path(ledger_file).read_text())
    published=set(map(str,ledger['published_source_ids'])); result={'registered':0,'missing':0,'excluded':0}
    for item in source['pending']:
        post=str(item['post_id']); path=Path(clips_dir)/(post+'.mp4')
        if post in published: result['excluded']+=1; continue
        if not path.is_file(): result['missing']+=1; continue
        queue.register(post,path.read_bytes(),published); result['registered']+=1
    return result
