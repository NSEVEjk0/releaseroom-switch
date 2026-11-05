from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from .artifact import canonical,sha,check,render,write_commit,verify_commit,policy_hash

class Conflict(ValueError):pass
class Forbidden(ValueError):pass

class Store:
    def __init__(self,root:Path,reviewers:set[str],requesters:set[str]|None=None,clock=time.time):
        self.root=root;self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.reviewers=reviewers;self.requesters=requesters or reviewers;self.clock=clock
        self.db=root/"release-room.sqlite3"
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS head(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
            INSERT OR IGNORE INTO head VALUES(1,0);
            CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,request TEXT NOT NULL,requester TEXT NOT NULL,
              content TEXT NOT NULL,state TEXT NOT NULL,created INTEGER NOT NULL,report TEXT,manifest TEXT,digest TEXT,git_commit TEXT,
              approval TEXT,receipt TEXT);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,release_id TEXT,kind TEXT,actor TEXT,data TEXT,created INTEGER);
            CREATE TABLE IF NOT EXISTS incoming(agent TEXT,message_id TEXT,body TEXT,state TEXT,PRIMARY KEY(agent,message_id));
            CREATE TABLE IF NOT EXISTS connections(agent TEXT PRIMARY KEY,connection_id TEXT,cursor INTEGER,generation INTEGER,halted INTEGER,gapped INTEGER DEFAULT 0,connected INTEGER DEFAULT 0);
            ''')
        os.chmod(self.db,0o600)

    def connect(self):
        db=sqlite3.connect(self.db,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL");return db
    def _event(self,db,id:str,kind:str,actor:str,data:dict):
        db.execute("INSERT INTO events(release_id,kind,actor,data,created) VALUES(?,?,?,?,?)",(id,kind,actor,canonical(data).decode(),int(self.clock())))
    def _row(self,db,id:str):
        if not isinstance(id,str) or not __import__('re').fullmatch(r"[a-f0-9]{32}",id):raise ValueError("Invalid release ID.")
        row=db.execute("SELECT * FROM releases WHERE id=?",(id,)).fetchone()
        if not row:raise ValueError("Release not found.")
        return row
    def _healthy(self,db):
        if db.execute("SELECT 1 FROM connections WHERE halted=1 OR gapped=1 OR connected=0 LIMIT 1").fetchone():
            raise Conflict("Switch room context is unavailable or has a gap. Restore the connections and request fresh approval.")
    def get(self,id:str):
        with self.connect() as db:
            row=dict(self._row(db,id));row["current_revision"]=db.execute("SELECT revision FROM head WHERE id=1").fetchone()[0]
            for key in ("content","report","manifest","approval","receipt"):
                if row[key] is not None:row[key]=json.loads(row[key])
            return row
    def list(self):
        with self.connect() as db:ids=[r[0] for r in db.execute("SELECT id FROM releases ORDER BY revision DESC LIMIT 40")]
        return [self.get(id) for id in ids]
    def propose(self,request:str,content:dict,actor:str,expected_revision:int)->dict:
        if actor not in self.requesters:raise Forbidden("This sender cannot request a release.")
        if not isinstance(request,str) or not 1<=len(request)<=2000:raise ValueError("Request must contain 1–2,000 characters.")
        if not isinstance(content,dict) or len(canonical(content))>12_000:raise ValueError("Proposal must be a bounded JSON object.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision=db.execute("SELECT revision FROM head WHERE id=1").fetchone()[0]
            if revision!=expected_revision:raise Conflict("A newer request is already present.")
            if db.execute("SELECT 1 FROM releases WHERE state='publishing'").fetchone():raise Conflict("Finish or recover the in-progress publication first.")
            id=uuid.uuid4().hex;revision+=1
            db.execute("UPDATE releases SET state='superseded',approval=NULL WHERE state IN ('proposed','ready','approved','blocked')")
            db.execute("UPDATE head SET revision=? WHERE id=1",(revision,))
            db.execute("INSERT INTO releases(id,revision,request,requester,content,state,created) VALUES(?,?,?,?,?,'proposed',?)",(id,revision,request,actor,canonical(content).decode(),int(self.clock())))
            self._event(db,id,"builder_proposed",actor,{"revision":revision,"content_hash":sha(canonical(content))});db.commit()
        return self.get(id)
    def test(self,id:str)->dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE");row=self._row(db,id)
            if row["state"]!="proposed":raise Conflict("Only the current new proposal can be tested.")
            if row["revision"]!=db.execute("SELECT revision FROM head WHERE id=1").fetchone()[0]:raise Conflict("The proposal has been superseded.")
            content=json.loads(row["content"]);report=check(content)
            if not report["passed"]:
                db.execute("UPDATE releases SET report=?,state='blocked' WHERE id=?",(canonical(report).decode(),id))
                self._event(db,id,"tester_blocked","tester",{"policy_hash":report["policy_hash"]});db.commit();return self.get(id)
            data=render(content);folder=self.root/"artifacts"/id;folder.mkdir(parents=True,exist_ok=True)
            (folder/"index.html").write_bytes(data)
            prior=db.execute("SELECT git_commit FROM releases WHERE git_commit IS NOT NULL ORDER BY revision DESC LIMIT 1").fetchone()
            commit=write_commit(self.root/"artifact.git",content,data,row["revision"],row["created"],prior[0] if prior else None)
            manifest={"schema":"releaseroom-release-v1","id":id,"revision":row["revision"],"git_commit":commit,"artifact_sha256":sha(data),
                      "content_sha256":sha(canonical(content)),"policy_sha256":report["policy_hash"],"test_evidence_sha256":sha(canonical(report)),"request_sha256":sha(row["request"].encode())}
            digest=sha(canonical(manifest));(folder/"manifest.json").write_bytes(canonical(manifest))
            db.execute("UPDATE releases SET report=?,manifest=?,digest=?,git_commit=?,state='ready' WHERE id=?",(canonical(report).decode(),canonical(manifest).decode(),digest,commit,id))
            self._event(db,id,"tester_passed","tester",{"digest":digest});db.commit()
        return self.get(id)
    def _bound(self,row,db):
        if row["revision"]!=db.execute("SELECT revision FROM head WHERE id=1").fetchone()[0]:raise Conflict("The approved revision is no longer current.")
        m=json.loads(row["manifest"]);report=json.loads(row["report"]);content=json.loads(row["content"])
        data=(self.root/"artifacts"/row["id"]/"index.html").read_bytes()
        if sha(canonical(m))!=row["digest"] or m["policy_sha256"]!=policy_hash() or not report["passed"] or report!=check(content):
            raise Conflict("The checker policy or release manifest changed; retest and obtain new approval.")
        if m["id"]!=row["id"] or m["revision"]!=row["revision"] or m["git_commit"]!=row["git_commit"] or m["request_sha256"]!=sha(row["request"].encode()):
            raise Conflict("The manifest no longer binds this request and Git revision.")
        if m["test_evidence_sha256"]!=sha(canonical(report)) or m["content_sha256"]!=sha(canonical(content)) or m["artifact_sha256"]!=sha(data) or sha(render(content))!=sha(data):
            raise Conflict("Artifact, source or test evidence changed; retest and obtain new approval.")
        try:verify_commit(self.root/"artifact.git",m["git_commit"],content,data)
        except (ValueError,OSError):raise Conflict("The exact approved Git objects could not be verified.") from None
        return m,data
    def _approval(self,row):
        approval=json.loads(row["approval"])
        if approval["actor"] not in self.reviewers:raise Forbidden("The approving reviewer is no longer permitted.")
        if approval["digest"]!=row["digest"] or approval["expires_at"]<=int(self.clock()):raise Conflict("Approval expired or its binding changed.")
        return approval
    def _atomic(self,path:Path,data:bytes):
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            with temporary.open("xb") as output:output.write(data);output.flush();os.fsync(output.fileno())
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    def approve(self,id:str,digest:str,actor:str)->dict:
        if actor not in self.reviewers:raise Forbidden("Only a configured human Switch reviewer can approve.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE");row=self._row(db,id)
            if row["state"]!="ready" or digest!=row["digest"]:raise Conflict("Approval must name the complete current release fingerprint.")
            self._healthy(db)
            self._bound(row,db)
            approval={"actor":actor,"digest":digest,"approved_at":int(self.clock()),"expires_at":int(self.clock())+900}
            db.execute("UPDATE releases SET approval=?,state='approved' WHERE id=?",(canonical(approval).decode(),id))
            self._event(db,id,"human_approved",actor,{"digest":digest});db.commit()
        return self.get(id)
    def publish(self,id:str,recover:bool=False)->dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE");row=self._row(db,id)
            if row["state"]=="published":return json.loads(row["receipt"])
            self._healthy(db)
            if row["state"] not in ("approved","publishing"):raise Conflict("A current human approval is required.")
            if row["state"]=="publishing" and not recover:raise Conflict("This publication is already in progress.")
            self._approval(row)
            manifest,data=self._bound(row,db)
            db.execute("UPDATE releases SET state='publishing' WHERE id=?",(id,));db.commit()
        staging=self.root/"staging"/"releases"/id;staging.mkdir(parents=True,exist_ok=True)
        self._atomic(staging/"index.html",data);self._atomic(staging/"manifest.json",canonical(manifest))
        if sha((staging/"index.html").read_bytes())!=manifest["artifact_sha256"]:raise Conflict("Staging artifact failed the final hash check.")
        receipt={"release_id":id,"revision":manifest["revision"],"digest":sha(canonical(manifest)),"artifact_sha256":sha(data),"git_commit":manifest["git_commit"],"published_at":int(self.clock())}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE");row=self._row(db,id);self._healthy(db);self._approval(row);self._bound(row,db)
            if row["state"]!="publishing":raise Conflict("The publication claim is no longer active.")
            self._atomic(self.root/"staging"/"current.json",canonical(receipt))
            db.execute("UPDATE releases SET state='published',receipt=? WHERE id=?",(canonical(receipt).decode(),id))
            self._event(db,id,"staging_published","release-agent",receipt);db.commit()
        return receipt
    def recover_pending(self):
        """Operator recovery with workers stopped; never expose an expired approval."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows=db.execute("SELECT * FROM releases WHERE state='publishing'").fetchall()
            pointer=self.root/"staging"/"current.json"
            for row in rows:
                db.execute("UPDATE releases SET state='ready',approval=NULL WHERE id=?",(row['id'],))
                self._event(db,row['id'],'interrupted_publication_reset','operator',{'requires_fresh_approval':True})
            if rows:
                prior=db.execute("SELECT receipt FROM releases WHERE state='published' ORDER BY revision DESC LIMIT 1").fetchone()
                if prior:self._atomic(pointer,prior['receipt'].encode())
                else:pointer.unlink(missing_ok=True)
            db.commit()
        return {'reset':len(rows),'requires_fresh_approval':bool(rows)}
