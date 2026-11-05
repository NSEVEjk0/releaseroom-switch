import json
from urllib.parse import urlsplit,quote
from urllib.request import Request,build_opener,HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class SwitchHTTP:
    def __init__(self,base:str,agent:str,key:str,connection_id:str):
        p=urlsplit(base)
        if p.scheme not in ('http','https') or not p.netloc or p.username or p.password or p.query or p.fragment:raise ValueError('Invalid Switch base URL.')
        if p.scheme=='http' and p.hostname not in ('127.0.0.1','localhost'):raise ValueError('Remote Switch needs HTTPS.')
        self.base=base.rstrip('/');self.agent=quote(agent,safe='');self.key=key;self.connection_id=connection_id;self.registry=None
    def request(self,path:str,body:dict|None=None):
        headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','X-Switch-Connection-Id':self.connection_id}
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method='POST' if body is not None else 'GET')
        with build_opener(NoRedirect()).open(req,timeout=15) as response:
            data=response.read(1_048_577)
            if len(data)>1_048_576:raise ValueError('Switch response exceeds the supported size.')
            return json.loads(data)
    def discover(self):
        data=self.request('/agents/'+self.agent+'/ops');self.registry=data['operations']
        for name in ('connect_to_room','post_message','send_targeted_message','read_context'):
            if name not in self.registry:raise ValueError('This Switch server does not expose the required operation: '+name)
        return self.registry
    def op(self,name:str,args:dict):
        if self.registry is None:self.discover()
        if name not in self.registry:raise ValueError('Operation is not present in the server registry.')
        schema=self.registry[name].get('input_schema',{});properties=schema.get('properties',{})
        if set(args)-set(properties) or set(schema.get('required',[]))-set(args):raise ValueError('Operation arguments do not match the current server registry.')
        data=self.request('/agents/'+self.agent+'/ops/'+quote(name,safe=''),args)
        return data.get('result',data)
