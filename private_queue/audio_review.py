"""Verify a human's signed assertion about the exact source bytes.

A signature authenticates an attestation, not that someone actually listened.
No signing key is created here and no automated model provides clearance.
A trusted human reviewer and an independent, provisioned verification key are required.
"""
import base64,hashlib,json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def payload(candidate,digest):
    return json.dumps({'candidate':candidate,'sha256':digest,'scope':'entire_audio','verdict':'no_songs'},sort_keys=True,separators=(',',':')).encode('utf-8')


def verifier(public_key_b64):
    try:
        raw=base64.b64decode(public_key_b64,validate=True)
        pub=Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        return None
    def verify(item,data,proof):
        try:
            candidate=str(item['post_id'])+':'+str(item['media_id'])
            if not isinstance(proof,dict) or set(proof)!={'candidate','sha256','scope','verdict','signature'}: return False
            if proof['candidate']!=candidate or proof['sha256']!=hashlib.sha256(data).hexdigest() or proof['scope']!='entire_audio' or proof['verdict']!='no_songs': return False
            pub.verify(base64.b64decode(proof['signature'],validate=True),payload(candidate,proof['sha256']))
            return True
        except Exception: return False
    return verify


def has_no_audio_track(item, data, proof=None):
    """Fail closed: valid video with no audio stream; no opinion on files with audio.

    Inspect exact downloaded bytes, not metadata from a different version. Never mute
    or alter a source; unknown, malformed, missing ffprobe and timeout all fail.
    """
    import subprocess,tempfile,os
    try:
        if not isinstance(data,bytes) or not data: return False
        with tempfile.TemporaryDirectory(prefix='audio-track-check-') as d:
            p=os.path.join(d,'input.mp4')
            with open(p,'wb') as f: f.write(data)
            r=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',p],capture_output=True,timeout=45,check=True)
            obj=json.loads(r.stdout); streams=obj.get('streams')
            if not isinstance(streams,list) or not streams: return False
            if any(not isinstance(st,dict) or not isinstance(st.get('codec_type'),str) for st in streams): return False
            if not any(st['codec_type']=='video' and st.get('codec_name') for st in streams): return False
            if any(st['codec_type']=='audio' for st in streams): return False
            duration=float(obj.get('format',{}).get('duration','0'))
            return duration>0
    except Exception: return False


def verifier_with_silent_sources(public_key_b64):
    human=verifier(public_key_b64)
    def verify(item,data,proof):
        return has_no_audio_track(item,data,proof) or (human is not None and human(item,data,proof))
    return verify
