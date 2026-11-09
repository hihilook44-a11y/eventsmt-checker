#!/usr/bin/env python3
"""Read known submissions and checkpoint confirmed publications; never create posts."""
from pathlib import Path
from secure_scan import read_key,load_snapshot
from workflow_pipeline import reconcile_known_deliveries
from git_checkpoint import encrypted_git_checkpoint
from woopsocial_adapter import Provider

def main():
    f=read_key();s=load_snapshot(f); p=Provider(); cp=lambda obj:encrypted_git_checkpoint(Path(__file__).resolve().parent.parent,f,obj)
    reconcile_known_deliveries(s,cp,p)
    for r in s.get('candidate_deliveries',{}).values():
        if r.get('state') in ('delivery_recorded','delivery_uncertain') and r.get('post_id'):
            post=p.post(r['post_id'])
            if post.get('id') != r['post_id'] or post.get('projectId') != r.get('project'):
                raise ValueError('provider identity mismatch')
            matches=[x for x in post.get('socialAccountPosts',[]) if x.get('socialAccountId')==r.get('account')]
            if len(matches)!=1: raise ValueError('provider destination mismatch')
            status=matches[0].get('deliveryStatus')
            print('Provider delivery status:', status if status in ('NOT_STARTED','SENDING','PUBLISHED','FAILED') else 'OTHER')
    for r in s.get('candidate_deliveries',{}).values():
        if r.get('state') in ('published','delivery_recorded','delivery_uncertain'):
            print('Delivery:',r['state'])
            if r.get('state')=='published' and r.get('external_post_url','').startswith(('https://www.youtube.com/','https://youtube.com/','https://youtu.be/')):
                print('YouTube:',r['external_post_url'])
if __name__=='__main__': main()
