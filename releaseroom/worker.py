from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from .protocol import ConnectionState,PermanentStop
from .http_client import SwitchHTTP
from .provider import Unavailable
from .store import Conflict,Forbidden

MARKER='[releaseroom]'

class AgentWorker:
    def __init__(self,store,profile:dict,all_profiles:dict,base:str,room:str,builder):
        self.store=store;self.profile=profile;self.profiles=all_profiles;self.room=room;self.builder=builder
        self.state=ConnectionState(store,profile['id'],room)
        self.http=SwitchHTTP(base,profile['id'],profile['api_key'],self.state.connection_id)
        self.role=profile['role'];self.stop=False
    async def op(self,name,args):return await asyncio.to_thread(self.http.op,name,args)
    async def reply(self,body,thread=None):return await self.op('post_message',{'body':body,'thread_id':thread})
    async def handoff(self,role,body,thread=None):
        return await self.op('send_targeted_message',{'body':body,'target_names':[self.profiles[role]['name']],'thread_id':thread})
    async def handle(self,data:dict):
        p=data['payload'];body=p['body'];sender=self.store.sender_ids.get(p['sender'],p['sender']);thread=p.get('thread_id') or p['message_id']
        if MARKER not in body:return
        command=body.split(MARKER,1)[1].strip()
        if self.state.gapped:raise Conflict('The room needs context recovery and a fresh request before approval.')
        if self.role=='builder' and command.startswith('request '):
            if sender not in self.store.requesters:raise Forbidden('This sender is not an allowed requester.')
            request=command[8:].strip()
            if not 1<=len(request)<=2000:raise ValueError('Use a request of 1–2,000 characters.')
            with self.store.connect() as db:
                self.store._healthy(db);revision=db.execute('SELECT revision FROM head WHERE id=1').fetchone()[0]
            proposed=await asyncio.to_thread(self.builder.propose,request)
            if self.stop or self.state.halted:raise Conflict('The connection stopped while building. Request a new release.')
            with self.store.connect() as db:self.store._healthy(db)
            release=await asyncio.to_thread(self.store.propose,request,proposed,sender,revision)
            await self.handoff('tester',MARKER+' test '+release['id'],thread)
        elif self.role=='tester' and re.fullmatch(r'test [a-f0-9]{32}',command):
            if sender!=self.profiles['builder']['participant_id']:raise Forbidden('Only the configured builder can hand off a proposal.')
            release=await asyncio.to_thread(self.store.test,command.split()[1])
            if release['state']=='blocked':
                failed=', '.join(t['name'] for t in release['report']['tests'] if not t['passed'])
                await self.reply('Release blocked by independent checks: '+failed+'. Request a revised proposal.',thread)
            else:await self.handoff('release',MARKER+' ready '+release['id']+' '+release['digest'],thread)
        elif self.role=='release' and re.fullmatch(r'ready [a-f0-9]{32} [a-f0-9]{64}',command):
            if sender!=self.profiles['tester']['participant_id']:raise Forbidden('Only the configured tester can announce checked work.')
            _,id,digest=command.split();release=self.store.get(id)
            if release['state']!='ready' or digest!=release['digest']:raise Conflict('The checked release has been superseded.')
            await self.reply('Ready for human review. Revision '+str(release['revision'])+', commit '+release['git_commit']+'.\nArtifact SHA256 '+release['manifest']['artifact_sha256']+'\nApprove this exact release with:\n'+MARKER+' approve '+id+' '+digest+'\nApproval expires after 15 minutes and any content change requires new approval.',thread)
        elif self.role=='release' and re.fullmatch(r'approve [a-f0-9]{32} [a-f0-9]{64}',command):
            _,id,digest=command.split();await asyncio.to_thread(self.store.approve,id,digest,sender)
            receipt=await asyncio.to_thread(self.store.publish,id)
            await self.reply('Staging release published: revision '+str(receipt['revision'])+'; artifact '+receipt['artifact_sha256']+'. The staging view serves only this fingerprint.',thread)
    async def pending(self):
        while not self.stop:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute("SELECT message_id,body FROM incoming WHERE agent=? AND state='pending' ORDER BY rowid LIMIT 1",(self.profile['id'],)).fetchone()
                if row:db.execute("UPDATE incoming SET state='working' WHERE agent=? AND message_id=?",(self.profile['id'],row['message_id']))
                db.commit()
            if not row:await asyncio.sleep(.2);continue
            result='done'
            try:await self.handle(json.loads(row['body']))
            except (Conflict,Forbidden,Unavailable,ValueError) as error:
                result='rejected'
                try:await self.reply(str(error),json.loads(row['body'])['payload'].get('thread_id'))
                except Exception:result='uncertain'
            except Exception:result='uncertain'
            with self.store.connect() as db:db.execute('UPDATE incoming SET state=? WHERE agent=? AND message_id=?',(result,self.profile['id'],row['message_id']))
    async def snapshot(self,operation,args,suffix):
        try:
            context=await self.op(operation,args)
            folder=self.store.root/'recovery';folder.mkdir(exist_ok=True)
            path=folder/(self.role+'-'+suffix+'.json');path.write_text(json.dumps(context));path.chmod(0o600)
            with self.store.connect() as db:self.store._event(db,None,'switch_context_saved',self.profile['id'],{'operation':operation,'file':path.name})
        except Exception as error:
            with self.store.connect() as db:self.store._event(db,None,'switch_context_failed',self.profile['id'],{'operation':operation,'error_type':type(error).__name__})
    async def run(self):
        from websockets.asyncio.client import connect
        if self.state.halted:raise PermanentStop('This persisted connection was taken over or permanently stopped.')
        await asyncio.to_thread(self.http.discover)
        pending=asyncio.create_task(self.pending())
        try:
            while not self.stop:
                try:
                    async with connect(self.state.url(self.http.base),additional_headers={'Authorization':'Bearer '+self.profile['api_key']},max_size=1_048_576,ping_interval=None,open_timeout=15) as socket:
                        async for raw in socket:
                            frame=json.loads(raw);reply=self.state.frame(frame)
                            if reply is not None:await socket.send(json.dumps(reply))
                            if frame.get('event',frame.get('type'))=='gap':
                                asyncio.create_task(self.snapshot('read_context',{'limit':200,'room_id':self.room},'context'))
                            if frame.get('event',frame.get('type'))=='connection_state':
                                asyncio.create_task(self.snapshot('connect_to_room',{'room_id':self.room},'room'))
                except PermanentStop:raise
                except Exception:
                    self.state.disconnected();await asyncio.sleep(3)
        finally:self.stop=True;pending.cancel();self.state.disconnected()
