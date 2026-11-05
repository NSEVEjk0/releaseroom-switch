import argparse
import asyncio
import json
import os
from pathlib import Path
from .store import Store
from .provider import BuilderProvider
from .worker import AgentWorker
from .demo import run,verify
from .setup import validate_profiles,resolve_profiles,private_json,operator_lock

def settings():
    root=Path(os.getenv('RELEASEROOM_STATE_DIR','.local/state'))
    reviewers=set(json.loads(os.getenv('RELEASEROOM_REVIEWERS','[]')))
    requesters=set(json.loads(os.getenv('RELEASEROOM_REQUESTERS','[]')))
    store=Store(root,reviewers,requesters or reviewers)
    profile_file=Path(os.getenv('RELEASEROOM_AGENT_FILE','.local/switch-agents.json'))
    profiles=json.loads(profile_file.read_text()) if profile_file.is_file() else {}
    key_file=os.getenv('RELEASEROOM_VULTR_KEY_FILE')
    builder=BuilderProvider(store,Path(key_file) if key_file else None)
    return store,profiles,builder

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['demo','verify','run','serve','doctor','resync','recover','resolve-profiles'])
    parser.add_argument('file',nargs='?');args=parser.parse_args()
    if args.command=='demo':
        root=Path(os.getenv('RELEASEROOM_DEMO_DIR','.local/reference'))
        bundle=run(root);destination=Path(args.file or 'reports/reference-release.json');destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(bundle,indent=2))
        print(json.dumps(verify(bundle)));return
    if args.command=='verify':print(json.dumps(verify(json.loads(Path(args.file).read_text()))));return
    store,profiles,builder=settings();base=os.getenv('RELEASEROOM_SWITCH_URL','');room=os.getenv('RELEASEROOM_ROOM_ID','')
    if args.command=='doctor':
        try:validate_profiles(profiles,store.reviewers);ready=True
        except ValueError:ready=False
        with store.connect() as db:
            context=[{'kind':r['kind'],'actor':r['actor'],'data':json.loads(r['data'])} for r in db.execute("SELECT kind,actor,data FROM events WHERE kind LIKE 'switch_context_%' ORDER BY seq DESC LIMIT 6")]
        print(json.dumps({'switch_profiles_ready':ready,'room_configured':bool(base and room),'model_available':builder.available,'reviewers_configured':bool(store.reviewers),'context_status':context}));return
    if args.command=='serve':
        from .server import serve
        serve(store,profiles,builder);return
    if args.command=='resync':
        if not args.file or not Path(args.file).is_file():raise SystemExit('Read and provide the recovered room-context JSON before resetting a gap.')
        history=json.loads(Path(args.file).read_text())
        if history.get('truncated') is not False:raise SystemExit('The recovered history is partial. Read the full context first.')
        with operator_lock(store.root):
            store.recover_pending()
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE');db.execute("UPDATE releases SET state='superseded',approval=NULL WHERE state IN ('ready','approved','proposed','blocked')")
                db.execute('UPDATE head SET revision=revision+1 WHERE id=1');db.execute('UPDATE connections SET gapped=0');db.commit()
        print('Gap cleared; the next release requires a fresh request and human approval.');return
    if args.command=='recover':
        with operator_lock(store.root):print(json.dumps(store.recover_pending()))
        return
    if args.command=='resolve-profiles':
        if not args.file:raise SystemExit('Supply an exported list_participants JSON file from the actual room.')
        resolved,humans=resolve_profiles(profiles,json.loads(Path(args.file).read_text()))
        with operator_lock(store.root):private_json(Path(os.getenv('RELEASEROOM_AGENT_FILE','.local/switch-agents.json')),resolved)
        print(json.dumps({'profiles_resolved':True,'human_reviewers_to_choose':humans}));return
    if set(profiles)!={'builder','tester','release'} or not base or not room or not store.reviewers:raise SystemExit('Complete the operator Switch profiles, room and reviewer settings first.')
    validate_profiles(profiles,store.reviewers)
    with store.connect() as db:db.execute("UPDATE incoming SET state='uncertain' WHERE state='working'")
    async def workers():await asyncio.gather(*(AgentWorker(store,{**profile,'role':role},profiles,base,room,builder).run() for role,profile in profiles.items()))
    with operator_lock(store.root):
        store.recover_pending()
        asyncio.run(workers())

if __name__=='__main__':main()
