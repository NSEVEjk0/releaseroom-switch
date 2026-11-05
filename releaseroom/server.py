import hashlib
import hmac
import json
import mimetypes
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .artifact import sha

WEB=Path(__file__).resolve().parent.parent/'web'

def serve(store,profiles,builder):
    origin=os.getenv('RELEASEROOM_ORIGIN','http://127.0.0.1:8090')
    token_file=Path(os.getenv('RELEASEROOM_ACCESS_FILE','.local/team-access.txt'))
    def token():return token_file.read_text().strip() if token_file.is_file() else ''
    def session():return hashlib.sha256(('ReleaseRoom session:'+token()).encode()).hexdigest() if token() else ''
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,kind='application/json',headers=None):
            if kind=='application/json' and not isinstance(data,bytes):data=json.dumps(data).encode()
            elif isinstance(data,str):data=data.encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Cache-Control','no-store' if kind=='application/json' else 'no-cache')
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(data)
        def authorized(self):
            cookie=SimpleCookie()
            try:cookie.load(self.headers.get('Cookie',''))
            except Exception:return False
            value=cookie.get('releaseroom_session')
            return bool(value and session() and hmac.compare_digest(value.value,session()))
        def do_POST(self):
            if self.path!='/api/session':self.send(405,{'error':'Release requests and approvals come through the configured Switch room.'});return
            if self.headers.get('Origin')!=origin:self.send(403,{'error':'Open the team page at its configured address.'});return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=2048:raise ValueError()
                supplied=json.loads(self.rfile.read(size)).get('access_code','')
                if not isinstance(supplied,str) or not token() or not hmac.compare_digest(supplied,token()):self.send(401,{'error':'Team access was not accepted.'});return
            except (ValueError,TypeError):self.send(400,{'error':'Invalid access request.'});return
            secure='; Secure' if origin.startswith('https:') else ''
            self.send(200,{'connected':True},headers={'Set-Cookie':'releaseroom_session='+session()+'; Path=/; HttpOnly; SameSite=Strict'+secure})
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/api/config':
                with store.connect() as db:connections=[dict(r) for r in db.execute('SELECT connected,gapped,halted FROM connections')]
                switch=bool(len(connections)==3 and all(c['connected'] and not c['gapped'] and not c['halted'] for c in connections))
                self.send(200,{'deployment':'controller','available':switch and builder.available,'switch_connected':switch,'model_available':builder.available,'authenticated':self.authorized()});return
            if path=='/api/releases':
                if not self.authorized():self.send(401,{'error':'Unlock your team workspace to read live releases.'});return
                self.send(200,{'releases':store.list()});return
            if path=='/staging' or path=='/staging/':
                try:
                    receipt=json.loads((store.root/'staging/current.json').read_text());id=receipt['release_id']
                    row=store.get(id)
                    if row['state']!='published' or row['receipt']['digest']!=receipt['digest']:raise ValueError()
                    data=(store.root/'staging/releases'/id/'index.html').read_bytes()
                    if sha(data)!=receipt['artifact_sha256']:raise ValueError()
                    self.send(200,data,'text/html; charset=utf-8',{'X-Robots-Tag':'noindex','X-ReleaseRoom-Artifact':receipt['artifact_sha256']})
                except (FileNotFoundError,ValueError,KeyError):self.send(503,{'error':'No verified published staging artifact is available.'})
                return
            file=(WEB/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not file.is_relative_to(WEB.resolve()) or not file.is_file():self.send(404,{'error':'Not found.'});return
            self.send(200,file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
    ThreadingHTTPServer((os.getenv('RELEASEROOM_HOST','127.0.0.1'),int(os.getenv('RELEASEROOM_PORT','8090'))),Handler).serve_forever()
