import asyncio
import json
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from websockets.asyncio.server import serve
from releaseroom.store import Store
from releaseroom.worker import AgentWorker
from releaseroom.protocol import PermanentStop
from releaseroom.artifact import DEFAULT

class SlowFixtureBuilder:
    def propose(self,request):time.sleep(2);return DEFAULT.copy()

class SocketTest(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_websocket_keeps_pongs_flowing_during_builder_work(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder),{'opaque-human'})
            profile={'id':'fixture-builder-id','api_key':'fixture-only-not-a-live-key','name':'fixture-builder','role':'builder','participant_id':'opaque-builder'}
            profiles={'builder':profile,'tester':{'name':'fixture-tester','participant_id':'opaque-tester'},'release':{'name':'fixture-release','participant_id':'opaque-release'}}
            pongs=[];calls=[]
            schemas={'connect_to_room':{'room_id':{}},'post_message':{'body':{},'thread_id':{}},'send_targeted_message':{'body':{},'target_names':{},'thread_id':{}},'read_context':{'limit':{},'room_id':{}}}
            async def process(connection,request):
                self.assertEqual(request.headers.get('Authorization'),'Bearer '+profile['api_key'])
                if '/connection/ws?' in request.path:return None
                if request.path.endswith('/ops'):body={'operations':{name:{'input_schema':{'properties':fields}} for name,fields in schemas.items()}}
                else:
                    calls.append(request.path);body={'result':{'room_id':'fixture-room','participants':[],'threads':[],'truncated':False}}
                return connection.respond(HTTPStatus.OK,json.dumps(body))
            async def socket(connection):
                params=parse_qs(urlsplit(connection.request.path).query)
                self.assertEqual(params['rooms'],['fixture-room']);self.assertEqual(params['filter'],['all'])
                await connection.send(json.dumps({'event':'connection_state','data':{'connection_id':params['connection_id'][0],'agent_id':profile['id'],'generation':3,'cursor':0,'rooms':['fixture-room']}}))
                await connection.send(json.dumps({'event':'message','id':1,'data':{'type':'message','room_id':'fixture-room','sequence':1,'payload':{'addressed':True,'sender':'opaque-human','sender_name':'Fixture reviewer','message_id':'fixture-message','body':'[releaseroom] request A new headline','timestamp':1,'thread_id':None,'attachments':[]}}}))
                for _ in range(3):
                    await connection.send(json.dumps({'event':'ping','data':{}}));pongs.append(json.loads(await asyncio.wait_for(connection.recv(),.8)));await asyncio.sleep(.15)
                await connection.send(json.dumps({'event':'evicted','data':{'code':'taken_over'}}))
            async with serve(socket,'127.0.0.1',0,process_request=process) as server:
                port=server.sockets[0].getsockname()[1]
                worker=AgentWorker(store,profile,profiles,f'http://127.0.0.1:{port}','fixture-room',SlowFixtureBuilder())
                with self.assertRaises(PermanentStop):await asyncio.wait_for(worker.run(),8)
            self.assertEqual(pongs,[{'type':'pong','cursor':1}]*3)
            self.assertTrue(any('connect_to_room' in call for call in calls))
            self.assertTrue(worker.state.halted)

if __name__=='__main__':unittest.main()
