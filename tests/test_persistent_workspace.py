"""Real auth + persistence tests; model calls are mocked. Never use your live DB."""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Set a disposable DB BEFORE importing app modules.
import tempfile
TEMP = tempfile.TemporaryDirectory(prefix="zero-magic-tests-")
os.environ.setdefault("ZERO_MAGIC_DB", str(Path(TEMP.name)/"tests.sqlite3"))
from app import assistant, storage
from app.storage import Counter
from app.main import app

PASSWORD="test-passphrase-12345"


@pytest.fixture(autouse=True)
def reset():
    with storage.lock,storage.connection() as db:
        for table in ("sessions","invitations","users","login_attempts","proposals","comments","cards","people","counters"):
            db.execute(f"DELETE FROM {table}")
    for data in (storage.cards,storage.people,storage.comments,storage.proposals):data.clear()
    storage.card_ids=Counter(1);storage.comment_ids=Counter(1);storage.person_ids=Counter(1)
    yield


def owner():
    client=TestClient(app)
    result=client.post('/api/v1/auth/setup',json={"username":"owner","password":PASSWORD,"name":"Saba"})
    assert result.status_code==201,result.text
    return client,result.json()


def card(client,title="Build notifications"):
    r=client.post('/api/v1/cards',json={"title":title,"goal":"Keep people informed"})
    assert r.status_code==201,r.text
    return r.json()


def teammate(client):
    person=client.post('/api/v1/people',json={"name":"Sara","skills":["CSS"]}).json()
    invitation=client.post('/api/v1/auth/invitations',json={"person_id":person['id']}).json()
    second=TestClient(app)
    r=second.post('/api/v1/auth/accept-invite',json={"username":"sara","password":PASSWORD,"token":invitation['token']})
    assert r.status_code==201,r.text
    return second,r.json(),invitation


def mock_plan(monkeypatch):
    monkeypatch.setattr(assistant,'ask_model',lambda *a,**kw:{"model":"mock","message":json.dumps({"cards":[{"title":"Implement the new plan","goal":"Create a small version","acceptance_criteria":["A user can save changes"],"out_of_scope":""}]})})


def preview(client,monkeypatch):
    mock_plan(monkeypatch)
    convo=str(uuid4())
    r=client.post('/api/v1/assistant/chat',json={"conversation_id":convo,"messages":[{"role":"user","content":"Deploy the agreed plan"}],"mode":"plan"})
    assert r.status_code==200,r.text
    return convo,r.json()['proposal']['id']


def approve(client,convo,ident):
    return client.post(f'/api/v1/assistant/proposals/{ident}/confirm',json={"conversation_id":convo,"approve":True})


@pytest.mark.parametrize('path',['/api/v1/cards','/api/v1/people','/api/v1/auth/me'])
def test_private_reads(path):
    assert TestClient(app).get(path).status_code==401


def test_private_write():
    assert TestClient(app).post('/api/v1/cards',json={"title":"No","goal":"No"}).status_code==401


def test_setup_once_and_password_hash():
    c,u=owner()
    assert c.post('/api/v1/auth/setup',json={"username":"other","password":PASSWORD,"name":"Other"}).status_code==409
    with storage.connection() as db:
        row=db.execute('SELECT password_hash FROM users').fetchone()
        assert row[0].startswith('scrypt$') and PASSWORD not in row[0]
        assert db.execute('SELECT token_hash FROM sessions').fetchone()[0]!=c.cookies.get('zero_magic_session')
    assert c.get('/api/v1/auth/me').json()['person_id']==u['person_id']


def test_cookie_and_logout_revocation():
    c,u=owner();token=c.cookies.get('zero_magic_session')
    c.post('/api/v1/auth/logout',json={})
    c.cookies.set('zero_magic_session',token)
    assert c.get('/api/v1/auth/me').status_code==401
    r=c.post('/api/v1/auth/login',json={"username":"OWNER","password":PASSWORD})
    assert r.status_code==200
    cookie=r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=2592000' in cookie


def test_wrong_password_generic():
    c,u=owner()
    for name in ['owner','unknown']:
        r=c.post('/api/v1/auth/login',json={"username":name,"password":"wrong-passphrase-123"})
        assert r.status_code==401 and r.json()['detail']=='Username or password is incorrect.'


def test_expired_session():
    c,u=owner()
    with storage.connection() as db:db.execute('UPDATE sessions SET expires=0')
    assert c.get('/api/v1/cards').status_code==401


def test_rate_limit():
    c,u=owner()
    with storage.connection() as db:db.executemany('INSERT INTO login_attempts VALUES (?,?)', [('ip:testclient',time.time())]*20)
    assert c.post('/api/v1/auth/login',json={"username":"owner","password":PASSWORD}).status_code==429


def test_invite_once_and_owner_permissions():
    c,u=owner();second,other,invite=teammate(c)
    assert second.get('/api/v1/auth/me').json()['name']=='Sara'
    assert second.post('/api/v1/auth/accept-invite',json={"username":"another","password":PASSWORD,"token":invite['token']}).status_code==409
    assert second.post('/api/v1/people',json={"name":"Imposter"}).status_code==403
    assert second.post('/api/v1/auth/invitations',json={"person_id":u['person_id']}).status_code==403
    assert second.put(f'/api/v1/people/{u["person_id"]}',json={"name":"Fake"}).status_code==403
    assert second.put(f'/api/v1/people/{other["person_id"]}',json={"name":"Sara","skills":["Vue"]}).status_code==200


def test_regenerating_invite_revokes_old():
    c,u=owner();p=c.post('/api/v1/people',json={"name":"Ali"}).json()
    first=c.post('/api/v1/auth/invitations',json={"person_id":p['id']}).json()['token']
    second=c.post('/api/v1/auth/invitations',json={"person_id":p['id']}).json()['token']
    assert c.post('/api/v1/auth/invitation',json={"token":first}).status_code==404
    assert c.post('/api/v1/auth/invitation',json={"token":second}).status_code==200


def test_expired_invite():
    c,u=owner();p=c.post('/api/v1/people',json={"name":"Ali"}).json();token=c.post('/api/v1/auth/invitations',json={"person_id":p['id']}).json()['token']
    with storage.connection() as db:db.execute('UPDATE invitations SET expires=0')
    assert c.post('/api/v1/auth/accept-invite',json={"token":token,"username":"ali","password":PASSWORD}).status_code==409


def test_server_controls_comment_identity():
    c,u=owner();second,other,_=teammate(c);created=card(c)
    url=f'/api/v1/cards/{created["id"]}/comments'
    r=second.post(url,json={"text":"I can handle the interface."})
    assert r.status_code==201,r.text
    assert r.json()['author']=='Sara' and r.json()['author_id']==other['person_id'] and r.json()['user_id']==other['id']
    assert r.json()['created_at']
    assert second.post(url,json={"text":"Fake","author":"Saba","author_id":u['person_id']}).status_code==422
    assert c.get('/api/v1/cards').json()[0]['comment_count']==1


@pytest.mark.parametrize('headers,code', [({'origin':'https://evil.example'},403),({'sec-fetch-site':'cross-site'},403),({'content-type':'text/plain'},415)])
def test_csrf_guards(headers,code):
    c,u=owner()
    assert c.post('/api/v1/cards',json={"title":"No","goal":"No"},headers=headers).status_code==code


def test_trusted_host():
    assert TestClient(app,base_url='http://evil.example').get('/').status_code==400


def test_crud_and_rules():
    c,u=owner();created=card(c);ident=created['id']
    assert c.patch(f'/api/v1/cards/{ident}',json={"title":"Edited"}).json()['goal']==created['goal']
    assert c.patch(f'/api/v1/cards/{ident}',json={"title":None}).status_code==422
    assert c.patch(f'/api/v1/cards/{ident}/stage',json={"stage":"Done"}).status_code==409
    assert c.patch(f'/api/v1/cards/{ident}/stage',json={"stage":"Ready"}).status_code==200
    assert c.request('DELETE',f'/api/v1/cards/{ident}',json={}).status_code==204
    assert c.get(f'/api/v1/cards/{ident}').status_code==404


def test_proposal_no_write_until_approved_and_separate_assignment(monkeypatch):
    c,u=owner();convo,ident=preview(c,monkeypatch)
    assert c.get('/api/v1/cards').json()==[]
    r=approve(c,convo,ident);assert r.status_code==200,r.text
    created=r.json()['cards'][0];assert created['assignee'] is None
    assert approve(c,convo,ident).json()==r.json()
    monkeypatch.setattr(assistant,'ask_model',lambda *a,**kw:{"model":"mock","message":json.dumps({"assignments":[{"card_id":created['id'],"person_id":u['person_id'],"reason":"Owner has context"}]})})
    draft=c.post('/api/v1/assistant/chat',json={"conversation_id":convo,"mode":"assign","target_card_ids":[created['id']],"messages":[{"role":"user","content":"Suggest owner"}]}).json()['proposal']
    assert c.get('/api/v1/cards').json()[0]['assignee'] is None
    assert approve(c,convo,draft['id']).status_code==200
    assert c.get('/api/v1/cards').json()[0]['assignee']['identifier']==str(u['person_id'])


def test_proposal_account_bound(monkeypatch):
    c,u=owner();second,other,_=teammate(c);convo,ident=preview(c,monkeypatch)
    assert approve(second,convo,ident).status_code==404
    assert approve(c,convo,ident).status_code==200


def test_stale_preview(monkeypatch):
    c,u=owner();convo,ident=preview(c,monkeypatch);card(c)
    assert approve(c,convo,ident).status_code==409
    assert len(storage.cards)==1


def test_batch_rolls_back_on_disk_failure(monkeypatch):
    c,u=owner();convo,ident=preview(c,monkeypatch)
    original=storage.flush
    def fail(db):
        original(db)
        raise RuntimeError('Simulated disk failure')
    monkeypatch.setattr(storage,'flush',fail)
    failing=TestClient(app,raise_server_exceptions=False);failing.cookies.update(c.cookies)
    assert approve(failing,convo,ident).status_code==500
    assert not storage.cards
    assert storage.proposals[ident]['status']=='pending'
    with storage.connection() as db:assert db.execute('SELECT count(*) FROM cards').fetchone()[0]==0


def test_concurrent_confirm_once(monkeypatch):
    c,u=owner();convo,ident=preview(c,monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:approve(c,convo,ident),range(2)))
    assert all(r.status_code==200 for r in results)
    assert results[0].json()==results[1].json() and len(storage.cards)==1


def test_real_process_restart_preserves_data_sessions_and_receipt(monkeypatch):
    c,u=owner();created=card(c)
    c.post(f'/api/v1/cards/{created["id"]}/comments',json={"text":"Persist me"})
    convo,ident=preview(c,monkeypatch);receipt=approve(c,convo,ident).json()
    token=c.cookies.get('zero_magic_session')
    code='''
import json,sys
from fastapi.testclient import TestClient
from app.main import app
c=TestClient(app);c.cookies.set("zero_magic_session",sys.argv[1])
assert c.get("/api/v1/auth/me").status_code==200
cards=c.get("/api/v1/cards").json();assert len(cards)==2
assert c.get("/api/v1/cards/1/comments").json()[0]["text"]=="Persist me"
r=c.post("/api/v1/assistant/proposals/"+sys.argv[3]+"/confirm",json={"conversation_id":sys.argv[2],"approve":True})
assert r.status_code==200,r.text
assert r.json()==json.loads(sys.argv[4])
assert len(c.get("/api/v1/cards").json())==2
new=c.post("/api/v1/cards",json={"title":"After restart","goal":"Keep unique IDs"}).json()
assert new["id"]==3
print("restart passed")
'''
    r=subprocess.run([sys.executable,'-c',code,token,convo,ident,json.dumps(receipt)],cwd=Path(__file__).resolve().parent.parent,env=os.environ.copy(),capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr


def test_deleted_ids_not_reused_after_restart():
    c,u=owner();created=card(c);c.request('DELETE',f'/api/v1/cards/{created["id"]}',json={})
    code='from app import storage;assert next(storage.card_ids)==2'
    r=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parent.parent,env=os.environ.copy(),capture_output=True,text=True)
    assert r.returncode==0,r.stderr


def test_existing_profile_can_become_owner():
    with storage.transaction():
        storage.people[7]={"id":7,"name":"Saba","skills":["Python"],"responsibility":"Intern"}
        storage.person_ids=Counter(8)
    c=TestClient(app)
    r=c.post('/api/v1/auth/setup',json={"name":"Saba","username":"saba","password":PASSWORD,"person_id":7})
    assert r.status_code==201,r.text
    assert r.json()['person_id']==7 and len(storage.people)==1


def test_legacy_import_and_consistent_backup(tmp_path):
    root=Path(__file__).resolve().parent.parent
    export=tmp_path/'workspace-export.json'
    export.write_text(json.dumps({"format":"zero-magic-export-v1","cards":[{"id":4,"title":"Old card","goal":"Keep my work","acceptance_criteria":[],"out_of_scope":"","stage":"Ready","assignee":{"kind":"human","identifier":"3"},"comment_count":1}],"people":[{"id":3,"name":"Saba","skills":["Python"],"responsibility":"Intern"}],"comments":[{"id":5,"card_id":4,"author":"Saba","author_id":3,"text":"Before logins","created_at":None}]}),encoding='utf-8')
    env={**os.environ,'ZERO_MAGIC_DB':str(tmp_path/'import.sqlite3')}
    first=subprocess.run([sys.executable,'scripts/import_workspace.py',str(export)],cwd=root,env=env,capture_output=True,text=True)
    assert first.returncode==0,first.stdout+first.stderr
    # Refuse to overwrite an existing workspace.
    again=subprocess.run([sys.executable,'scripts/import_workspace.py',str(export)],cwd=root,env=env,capture_output=True,text=True)
    assert again.returncode!=0 and 'empty database' in again.stderr
    code='''
from app import storage
from app.main import app
from fastapi.testclient import TestClient
assert storage.cards[4]["assignee"]["identifier"]=="3"
assert storage.comments[5]["user_id"] is None
assert next(storage.card_ids)==5
c=TestClient(app)
r=c.post("/api/v1/auth/setup",json={"username":"saba","name":"Saba","password":"test-passphrase-12345","person_id":3})
assert r.status_code==201,r.text
assert len(storage.people)==1
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    # sqlite backup API, same operation used by the private backup script.
    import sqlite3
    target=tmp_path/'backup.sqlite3'
    with sqlite3.connect(env['ZERO_MAGIC_DB']) as src,sqlite3.connect(target) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert dst.execute('SELECT count(*) FROM users').fetchone()[0]==1
        assert dst.execute('SELECT count(*) FROM cards').fetchone()[0]==1
