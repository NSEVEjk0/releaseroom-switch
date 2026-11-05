import json
from pathlib import Path
from .artifact import DEFAULT,sha,canonical
from .store import Store,Conflict

def run(root:Path)->dict:
    store=Store(root,{'fictional-example-reviewer'},clock=lambda:1793836800)
    with store.connect() as db:version=db.execute('SELECT revision FROM head WHERE id=1').fetchone()[0]
    first=store.propose('Make the CTA an invitation to build together.',{**DEFAULT,'cta':'Build together'},'fictional-example-reviewer',version)
    first=store.test(first['id']);store.approve(first['id'],first['digest'],'fictional-example-reviewer')
    newer=store.propose('Use Join the build night instead.',{**DEFAULT,'cta':'Join the build night'},'fictional-example-reviewer',version+1)
    try:store.publish(first['id']);raise AssertionError('A stale approval was accepted.')
    except Conflict as error:rejection=str(error)
    newer=store.test(newer['id']);store.approve(newer['id'],newer['digest'],'fictional-example-reviewer')
    receipt=store.publish(newer['id'])
    artifact=(root/'artifacts'/newer['id']/'index.html').read_text()
    bundle={'schema':'releaseroom-reference-v1','environment':'scripted-local-reference-no-Switch-no-AI',
            'earlier':{'digest':first['digest'],'revision':first['revision'],'content':first['content']},'stale_approval_rejection':rejection,
            'release':store.get(newer['id']),'receipt':receipt,'artifact':artifact}
    bundle['payload_sha256']=sha(canonical({k:v for k,v in bundle.items() if k!='payload_sha256'}))
    return bundle

def verify(bundle:dict):
    if bundle.get('schema')!='releaseroom-reference-v1':raise ValueError('Unknown bundle schema.')
    payload={k:v for k,v in bundle.items() if k!='payload_sha256'}
    if sha(canonical(payload))!=bundle['payload_sha256']:raise ValueError('Reference bundle was changed.')
    manifest=bundle['release']['manifest']
    if sha(canonical(manifest))!=bundle['release']['digest'] or sha(bundle['artifact'].encode())!=manifest['artifact_sha256']:raise ValueError('Artifact or manifest fingerprint differs.')
    if bundle['receipt']['digest']!=bundle['release']['digest']:raise ValueError('Receipt does not bind the same release.')
    return {'verified':True,'environment':bundle['environment'],'artifact_sha256':manifest['artifact_sha256']}
