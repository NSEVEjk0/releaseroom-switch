from __future__ import annotations
import json
import uuid
from urllib.parse import urlencode,quote,urlsplit

class PermanentStop(RuntimeError):pass

class ConnectionState:
    def __init__(self,store,agent:str,room:str):
        self.store=store;self.agent=agent;self.room=room
        with store.connect() as db:
            db.execute("INSERT OR IGNORE INTO connections(agent,connection_id,cursor,generation,halted,gapped,connected) VALUES(?,?,0,NULL,0,0,0)",(agent,str(uuid.uuid4())))
            row=db.execute("SELECT * FROM connections WHERE agent=?",(agent,)).fetchone()
        self.connection_id=row['connection_id'];self.cursor=row['cursor'];self.generation=row['generation']
        self.halted=bool(row['halted']);self.gapped=bool(row['gapped']);self.connected=False
    def save(self):
        with self.store.connect() as db:
            db.execute("UPDATE connections SET cursor=?,generation=?,halted=?,gapped=?,connected=? WHERE agent=?",(self.cursor,self.generation,int(self.halted),int(self.gapped),int(self.connected),self.agent))
    def url(self,base:str):
        parts=urlsplit(base)
        if parts.scheme not in ('http','https') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:raise ValueError('Use the configured Switch server base URL.')
        if parts.scheme=='http' and parts.hostname not in ('127.0.0.1','localhost'):raise ValueError('Remote Switch requires HTTPS.')
        args={'connection_id':self.connection_id,'scope':'single','filter':'all','rooms':self.room,'start_from':str(self.cursor) if self.cursor else 'head','client':'releaseroom','client_version':'1.0.0'}
        if self.generation is not None:args['expected_generation']=str(self.generation)
        scheme='wss' if parts.scheme=='https' else 'ws'
        return scheme+'://'+parts.netloc+parts.path.rstrip('/')+'/agents/'+quote(self.agent,safe='')+'/connection/ws?'+urlencode(args)
    def frame(self,frame:dict):
        kind=frame.get('event',frame.get('type'))
        data=frame.get('data',frame)
        if kind=='ping':return {'type':'pong','cursor':self.cursor}
        if kind=='connection_state':
            if data.get('connection_id')!=self.connection_id or data.get('agent_id')!=self.agent:raise PermanentStop('Switch returned a different connection identity.')
            self.generation=int(data['generation']);self.cursor=int(data['cursor'])
            self.connected=self.room in data.get('rooms',[]);self.save()
            if not self.connected:raise PermanentStop('The configured room was not claimed by this connection.')
        elif kind=='gap':
            self.cursor=int(data['resumed_at']);self.gapped=True;self.save()
            with self.store.connect() as db:
                db.execute("UPDATE releases SET state='ready',approval=NULL WHERE state='approved'")
        elif kind=='evicted':
            self.connected=False
            if data.get('code') in ('taken_over','closed'):self.halted=True
            self.save()
            if self.halted:raise PermanentStop('Switch ended this connection: '+str(data.get('code')))
        elif kind=='refused':
            self.connected=False;self.halted=True;self.save();raise PermanentStop('Switch refused the connection. Check the server-side access configuration.')
        elif kind in ('room_released','subscription_changed'):
            if (kind=='room_released' and data.get('room_id')==self.room) or (kind=='subscription_changed' and self.room not in data.get('rooms',[])):
                self.connected=False;self.save();raise PermanentStop('This connection no longer owns the configured room.')
        elif kind in ('message','command','room_join'):
            sequence=frame.get('id')
            if type(sequence) is not int or sequence!=data.get('sequence') or sequence<1:raise ValueError('Invalid Switch event sequence.')
            if sequence<=self.cursor:return None
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if kind=='message' and data.get('room_id')==self.room and data.get('payload',{}).get('addressed') is True:
                    payload=data['payload'];message_id=payload.get('message_id')
                    if not isinstance(message_id,str) or not isinstance(payload.get('sender'),str) or not isinstance(payload.get('body'),str):raise ValueError('Malformed addressed message.')
                    if len(payload['body'])<=4000:
                        db.execute("INSERT OR IGNORE INTO incoming(agent,message_id,body,state) VALUES(?,?,?,'pending')",(self.agent,message_id,json.dumps(data)))
                self.cursor=sequence
                db.execute('UPDATE connections SET cursor=? WHERE agent=?',(self.cursor,self.agent));db.commit()
        return None
    def resynchronized(self):
        self.gapped=False;self.save()
    def disconnected(self):self.connected=False;self.save()
