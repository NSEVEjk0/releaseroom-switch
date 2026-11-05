from __future__ import annotations
import hashlib
import html
import json
import re
import zlib
from pathlib import Path

POLICY = {"version":1,"schema":["headline","description","cta","background","foreground","link"],
          "headline_max":90,"description_max":240,"cta_max":40,"contrast_min":4.5,
          "destinations":["#join","/signup","/contact"],"renderer":"static-content-v1"}
DEFAULT = {"headline":"Make room for your next idea.","description":"A friendly place for people building something new.",
           "cta":"Join the community","background":"#eff3e9","foreground":"#17382e","link":"#join"}

def canonical(value:object)->bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def sha(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def policy_hash()->str:
    return sha(canonical({"policy":POLICY,"implementation":sha(Path(__file__).read_bytes())}))

def _luminance(color:str)->float:
    def part(channel:int)->float:
        c=channel/255
        return c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4
    r,g,b=(part(int(color[i:i+2],16)) for i in (1,3,5))
    return 0.2126*r+0.7152*g+0.0722*b

def check(content:dict)->dict:
    tests=[]
    def record(name:str,ok:bool,detail:str):tests.append({"name":name,"passed":bool(ok),"detail":detail})
    record("exact_content_schema",set(content)==set(POLICY["schema"]),"Only the six site-content fields are accepted.")
    for field,limit in (("headline",90),("description",240),("cta",40)):
        value=content.get(field)
        record(field+"_length",isinstance(value,str) and 0<len(value.strip())<=limit,f"1–{limit} nonempty characters.")
    colors_ok=all(isinstance(content.get(k),str) and bool(re.fullmatch(r"#[0-9a-fA-F]{6}",content[k])) for k in ("background","foreground"))
    record("hex_colors",colors_ok,"Two literal six-digit hex colors.")
    if colors_ok:
        a,b=sorted((_luminance(content["background"]),_luminance(content["foreground"])))
        contrast=(b+0.05)/(a+0.05)
        record("text_contrast",contrast>=4.5,f"WCAG contrast ratio {contrast:.3f}; minimum 4.5.")
    else:record("text_contrast",False,"Contrast cannot be measured without valid colors.")
    record("fixed_destination",content.get("link") in POLICY["destinations"],"CTA stays at a supported local destination.")
    return {"policy_hash":policy_hash(),"passed":all(t["passed"] for t in tests),"tests":tests}

def render(content:dict)->bytes:
    report=check(content)
    if not report["passed"]:raise ValueError("Content fails the independent check.")
    values={k:html.escape(v,quote=True) for k,v in content.items()}
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{values["headline"]}</title><style>body{{margin:0;background:{values["background"]};color:{values["foreground"]};font-family:system-ui,sans-serif}}'
            'main{max-width:850px;margin:12vh auto;padding:35px}h1{font-size:clamp(40px,7vw,72px);line-height:1.08;letter-spacing:-.05em}'
            'p{font-size:20px;line-height:1.6;max-width:580px}a{display:inline-block;color:inherit;border:1px solid;padding:15px 23px;margin-top:20px;border-radius:8px;text-decoration:none}'
            '</style></head><body><main><p>THE COMMUNITY / NEXT CHAPTER</p>'
            f'<h1>{values["headline"]}</h1><p>{values["description"]}</p><a href="{values["link"]}">{values["cta"]} ↗</a>'
            '<p id="join" style="font-size:12px;margin-top:60px">ReleaseRoom staging fixture. This page does not collect registrations.</p></main></body></html>').encode()

def git_object(directory:Path,kind:str,data:bytes)->str:
    raw=kind.encode()+b" "+str(len(data)).encode()+b"\0"+data
    digest=hashlib.sha1(raw).hexdigest();path=directory/"objects"/digest[:2]/digest[2:]
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(zlib.compress(raw))
    return digest

def write_commit(directory:Path,content:dict,artifact:bytes,revision:int,created:int,parent:str|None)->str:
    directory.mkdir(parents=True,exist_ok=True)
    (directory/"config").write_text("[core]\nrepositoryformatversion = 0\nbare = true\n")
    (directory/"HEAD").write_text("ref: refs/heads/artifacts\n")
    (directory/"refs"/"heads").mkdir(parents=True,exist_ok=True)
    entries=[]
    for name,data in sorted({"index.html":artifact,"site.json":canonical(content),"checker-policy.json":canonical(POLICY)}.items()):
        digest=git_object(directory,"blob",data)
        entries.append(b"100644 "+name.encode()+b"\0"+bytes.fromhex(digest))
    tree=git_object(directory,"tree",b"".join(entries))
    identity=f"ReleaseRoom <releases@localhost> {created} +0000"
    lines=[f"tree {tree}"]+([f"parent {parent}"] if parent else [])+[f"author {identity}",f"committer {identity}","",f"ReleaseRoom revision {revision}",""]
    commit=git_object(directory,"commit","\n".join(lines).encode())
    (directory/"refs"/"heads"/"artifacts").write_text(commit+"\n")
    return commit

def verify_commit(directory:Path,commit:str,content:dict,artifact:bytes)->None:
    def read(digest:str,kind:str)->bytes:
        if not re.fullmatch(r"[0-9a-f]{40}",digest):raise ValueError("Invalid Git object fingerprint.")
        try:raw=zlib.decompress((directory/"objects"/digest[:2]/digest[2:]).read_bytes())
        except zlib.error:raise ValueError("The pinned Git object cannot be decompressed.") from None
        header,data=raw.split(b"\0",1)
        if header!=kind.encode()+b" "+str(len(data)).encode() or hashlib.sha1(raw).hexdigest()!=digest:
            raise ValueError("The pinned Git object was changed.")
        return data
    data=read(commit,"commit")
    tree=data.split(b"\n",1)[0]
    if not tree.startswith(b"tree "):raise ValueError("Git commit has no root tree.")
    expected=[]
    for name,value in sorted({"index.html":artifact,"site.json":canonical(content),"checker-policy.json":canonical(POLICY)}.items()):
        raw=b"blob "+str(len(value)).encode()+b"\0"+value
        digest=hashlib.sha1(raw).hexdigest()
        if read(digest,"blob")!=value:raise ValueError("Git content differs from the checked artifact.")
        expected.append(b"100644 "+name.encode()+b"\0"+bytes.fromhex(digest))
    if read(tree[5:].decode(),"tree")!=b"".join(expected):raise ValueError("Git tree differs from the approved source and artifact.")
