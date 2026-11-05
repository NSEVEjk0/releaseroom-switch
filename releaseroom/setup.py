"""Resolve opaque Switch identities from an actual list_participants response."""
from __future__ import annotations
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

ROLES={'builder','tester','release'}

def validate_profiles(profiles:dict,reviewers:set[str]|None=None):
    if not isinstance(profiles,dict) or set(profiles)!=ROLES:raise ValueError('Configure exactly builder, tester and release profiles.')
    for profile in profiles.values():
        if not isinstance(profile,dict) or any(not isinstance(profile.get(k),str) or not profile[k].strip() for k in ('id','api_key','name','participant_id')):
            raise ValueError('Each profile needs id, api_key, exact room name and resolved participant_id.')
    for field in ('id','name','participant_id'):
        if len({p[field] for p in profiles.values()})!=3:raise ValueError('Agent identities and names must be distinct.')
    if reviewers and reviewers&{p['participant_id'] for p in profiles.values()}:
        raise ValueError('An agent cannot be a human release reviewer.')
    return True

def resolve_profiles(profiles:dict,participants:object):
    if isinstance(participants,dict):participants=participants.get('result',participants)
    if isinstance(participants,dict):participants=participants.get('participants')
    if not isinstance(participants,list) or not participants:raise ValueError('Provide the actual list_participants response from the configured room.')
    if set(profiles)!=ROLES:raise ValueError('Configure exactly the three agent roles first.')
    result={}
    for role,profile in profiles.items():
        matches=[p for p in participants if p.get('name')==profile.get('name') and p.get('type')=='agent']
        if len(matches)!=1 or not isinstance(matches[0].get('id'),str):raise ValueError('Each exact agent name must resolve to one opaque agent participant ID.')
        result[role]={**profile,'participant_id':matches[0]['id']}
    validate_profiles(result)
    humans=[{'id':p['id'],'name':p.get('name','')} for p in participants if p.get('type')=='user' and isinstance(p.get('id'),str)]
    return result,humans

def private_json(path:Path,value:object):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.new')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,'w') as output:json.dump(value,output,indent=2);output.flush();os.fsync(output.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

@contextmanager
def operator_lock(root:Path):
    import fcntl
    path=root/'workers.lock'
    with path.open('a') as file:
        try:fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Stop the existing workers before recovery, resync or profile changes.') from None
        try:yield
        finally:fcntl.flock(file,fcntl.LOCK_UN)
