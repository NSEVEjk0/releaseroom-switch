import asyncio
import json
import tempfile
import time
import threading
import unittest
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from websockets.asyncio.server import serve
from releaseroom.store import Store,Forbidden,Conflict
from releaseroom.worker import AgentWorker
from releaseroom.protocol import PermanentStop
from releaseroom.artifact import DEFAULT
from releaseroom.http_client import SwitchHTTP

class SlowFixtureBuilder:
    def propose(self,request):time.sleep(2);return DEFAULT.copy()

class SocketTest(unittest.IsolatedAsyncioTestCase):
    async def test_bridged_sender_ids_preserve_handoffs_and_only_the_human_can_approve(self):
        with tempfile.TemporaryDirectory() as folder:
            roles=('builder','tester','release')
            aliases={'transport-'+role:'opaque-'+role for role in roles}
            aliases['transport-human']='opaque-human'
            store=Store(Path(folder),{'opaque-human'},sender_ids=aliases)
            profiles={role:{'id':role+'-server','api_key':'fixture-only','name':role,
                            'participant_id':'opaque-'+role,'role':role} for role in roles}
            class FixtureBuilder:
                def propose(_,request):return {**DEFAULT,'cta':request}
            workers={role:AgentWorker(store,profiles[role],profiles,'http://127.0.0.1:1','fixture-room',FixtureBuilder()) for role in roles}
            replies=[]
            def message(sender,body):return {'payload':{'sender':sender,'sender_name':'Human-looking name',
                                        'body':body,'message_id':'fixture-message','thread_id':None}}
            for role,worker in workers.items():
                worker.state.connected=True;worker.state.save()
                async def handoff(target,body,thread=None,source=role):
                    return await workers[target].handle(message('transport-'+source,body))
                async def reply(body,thread=None):replies.append(body)
                worker.handoff=handoff;worker.reply=reply
            await workers['builder'].handle(message('transport-human','[releaseroom] request First invitation'))
            first=store.list()[0];self.assertEqual(first['state'],'ready')
            self.assertEqual(first['requester'],'opaque-human')
            first_command=f"[releaseroom] approve {first['id']} {first['digest']}"
            with self.assertRaises(Forbidden):await workers['release'].handle(message('transport-builder',first_command))
            with self.assertRaises(Forbidden):await workers['builder'].handle(message('unknown-person','[releaseroom] request Impersonation'))
            await workers['builder'].handle(message('transport-human','[releaseroom] request New invitation'))
            with self.assertRaises(Conflict):await workers['release'].handle(message('transport-human',f"[releaseroom] approve {first['id']}{first['digest']}"))
            current=store.list()[0]
            with self.assertRaises(Forbidden):await workers['release'].handle(message('transport-builder',f"[releaseroom] approve{current['id']}{current['digest']}"))
            with self.assertRaisesRegex(ValueError,'complete release ID and fingerprint'):
                await workers['release'].handle(message('transport-human',f"[releaseroom] approve{current['id']}{current['digest'][:-1]}"))
            self.assertEqual(store.get(current['id'])['state'],'ready')
            await workers['release'].handle(message('transport-human',f"[releaseroom] approve{current['id']}{current['digest']}"))
            self.assertEqual(store.get(current['id'])['state'],'published')
            self.assertTrue(any('Staging release published' in reply for reply in replies))

    async def test_authenticated_websocket_keeps_pongs_flowing_during_builder_work(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder),{'opaque-human'})
            profile={'id':'fixture-builder-id','api_key':'fixture-only-not-a-live-key','name':'fixture-builder','role':'builder','participant_id':'opaque-builder'}
            profiles={'builder':profile,'tester':{'name':'fixture-tester','participant_id':'opaque-tester'},'release':{'name':'fixture-release','participant_id':'opaque-release'}}
            pongs=[];calls=[]
            schemas={'connect_to_room':{'room_id':{}},'post_message':{'body':{},'thread_id':{}},'send_targeted_message':{'body':{},'target_names':{},'thread_id':{}},'read_context':{'limit':{},'room_id':{}}}
            case=self
            class HTTP(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    case.assertEqual(self.headers.get('Authorization'),'Bearer '+profile['api_key'])
                    body={'operations':{name:{'input_schema':{'properties':fields}} for name,fields in schemas.items()}}
                    self.respond(body)
                def do_POST(self):
                    case.assertEqual(self.headers.get('Authorization'),'Bearer '+profile['api_key'])
                    case.assertTrue(self.headers.get('X-Switch-Connection-Id'))
                    args=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    case.assertNotIn('arguments',args)
                    calls.append(self.path);self.respond({'result':{'room_id':'fixture-room','participants':[],'threads':[],'truncated':False}})
                def respond(self,body):
                    data=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            async def socket(connection):
                self.assertEqual(connection.request.headers.get('Authorization'),'Bearer '+profile['api_key'])
                params=parse_qs(urlsplit(connection.request.path).query)
                self.assertEqual(params['rooms'],['fixture-room']);self.assertEqual(params['filter'],['all'])
                await connection.send(json.dumps({'event':'connection_state','data':{'connection_id':params['connection_id'][0],'agent_id':profile['id'],'generation':3,'cursor':0,'rooms':['fixture-room']}}))
                await connection.send(json.dumps({'event':'message','id':1,'data':{'type':'message','room_id':'fixture-room','sequence':1,'payload':{'addressed':True,'sender':'opaque-human','sender_name':'Fixture reviewer','message_id':'fixture-message','body':'[releaseroom] request A new headline','timestamp':1,'thread_id':None,'attachments':[]}}}))
                for _ in range(3):
                    await connection.send(json.dumps({'event':'ping','data':{}}));pongs.append(json.loads(await asyncio.wait_for(connection.recv(),.8)));await asyncio.sleep(.15)
                await connection.send(json.dumps({'event':'evicted','data':{'code':'taken_over'}}))
            http=ThreadingHTTPServer(('127.0.0.1',0),HTTP);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            try:
                async with serve(socket,'127.0.0.1',0) as server:
                    port=server.sockets[0].getsockname()[1]
                    websocket_base=f'http://127.0.0.1:{port}'
                    worker=AgentWorker(store,profile,profiles,websocket_base,'fixture-room',SlowFixtureBuilder())
                    worker.http=SwitchHTTP(f'http://127.0.0.1:{http.server_port}',profile['id'],profile['api_key'],worker.state.connection_id)
                    original=worker.state.url;worker.state.url=lambda _:original(websocket_base)
                    with self.assertRaises(PermanentStop):await asyncio.wait_for(worker.run(),8)
            finally:http.shutdown();http.server_close();thread.join()
            self.assertEqual(pongs,[{'type':'pong','cursor':1}]*3)
            self.assertTrue(any('connect_to_room' in call for call in calls))
            self.assertTrue(worker.state.halted)

if __name__=='__main__':unittest.main()
