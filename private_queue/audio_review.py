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
