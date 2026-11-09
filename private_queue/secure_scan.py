#!/usr/bin/env python3
"""Authenticated-encrypted, fail-closed discovery only; never publish."""
import base64,json,os,subprocess,sys,tempfile,re
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

ROOT=Path(__file__).resolve().parent
ENCRYPTED=ROOT/'queue.enc'
KEY_ENV='PRIVATE_QUEUE_FERNET_KEY'

def read_key():
    key=os.environ.get(KEY_ENV,'').encode('ascii')
    try: return Fernet(key)
    except Exception: raise RuntimeError('private queue key unavailable or invalid') from None

def load_snapshot(fernet,path=None):
    path=ENCRYPTED if path is None else path
    try: raw=fernet.decrypt(path.read_bytes()); obj=json.loads(raw)
    except (InvalidToken,ValueError,OSError): raise RuntimeError('private queue authentication failed') from None
    if not isinstance(obj,dict) or not isinstance(obj.get('state'),dict) or not isinstance(obj.get('ledger'),dict):
        raise RuntimeError('invalid encrypted queue structure')
    state,ledger=obj['state'],obj['ledger']
    if not isinstance(state.get('pending'),list) or not isinstance(ledger.get('published_source_ids'),list):
        raise RuntimeError('invalid queue or publication ledger')
    return obj

def write_encrypted(fernet,obj,path=None):
    path=ENCRYPTED if path is None else path
    token=fernet.encrypt(json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode())
    tmp=path.with_suffix('.tmp'); tmp.write_bytes(token);os.replace(tmp,path)

def scan():
    f=read_key();snapshot=load_snapshot(f)
    # temp file lives only on the runner; never put plaintext into the checkout or log.
    with tempfile.TemporaryDirectory(prefix='private-eventsmt-') as d:
        base=Path(d); os.chmod(base,0o700)
        for name in ('candidates.py','paginated_candidates.py','incremental_queue.py','scheduled_private_scan.py'):
            (base/name).write_bytes((ROOT/name).read_bytes())
        for key,name in [('state','state.json'),('ledger','published_sources.json')]:
            p=base/name;p.write_text(json.dumps(snapshot[key],ensure_ascii=False));os.chmod(p,0o600)
        proc=subprocess.run([sys.executable,str(base/'scheduled_private_scan.py'),'--max-pages','5','--state',str(base/'state.json'),'--ledger',str(base/'published_sources.json')],capture_output=True,text=True,timeout=300)
        if proc.returncode:
            # Whitelist diagnostics: do not expose URLs, text, identifiers, or secrets.
            try:
                response=json.loads(proc.stdout)
                known=('Source scan failed','Insufficient page coverage to reach prior checkpoint','Invalid discovery checkpoint','Existing private baseline required')
                reasons=[name for name in known if any(name in item for item in response.get('reasons',[]) if isinstance(item,str))]
                reasons += [item for item in response.get('reasons',[]) if isinstance(item,str) and re.fullmatch(r'page=\d+ http=\d{3}',item)]
            except (ValueError,TypeError,AttributeError): reasons=[]
            print('Source scan incomplete; encrypted state preserved. Reasons: '+(', '.join(reasons) or 'scanner error'),file=sys.stderr);return 1
        try: result=json.loads(proc.stdout); updated=json.loads((base/'state.json').read_text())
        except (json.JSONDecodeError,OSError):
            print('Invalid scanner response; encrypted state preserved.',file=sys.stderr);return 1
        if not isinstance(updated.get('pending'),list): raise RuntimeError('invalid scanner output')
        snapshot['state']=updated
        write_encrypted(f,snapshot)
        print(json.dumps({k:result.get(k) for k in ('new_candidates','pending_total','pages_checked','page_size','more_pages_available','audio_verified','publication_performed')}))
    return 0
if __name__=='__main__':
    try: raise SystemExit(scan())
    except Exception as e:
        print('Private scan failed safely: '+type(e).__name__,file=sys.stderr);raise SystemExit(1)
