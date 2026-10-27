"""Project labels and deletions: real throwaway SQLite/auth, fake AI only."""
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app import storage,assistant,prds
from app.main import app

CONTENT='Goal: Build a small project dashboard for the existing signed-in team. Requirements: List tasks and show a useful empty state. Out of scope: Billing and email delivery.'
PASS='test-passphrase-12345'

@pytest.fixture(autouse=True)
def reset():
    with storage.lock,storage.connection() as db:
        for table in ('sessions','invitations','users','login_attempts','prd_generation_requests','prd_revisions','prds','proposals','comments','cards','people','counters','projects'):
            db.execute(f'DELETE FROM {table}')
    for records in (storage.cards,storage.people,storage.comments,storage.proposals,storage.prds,storage.projects):records.clear()
    storage.card_ids=storage.Counter();storage.person_ids=storage.Counter();storage.comment_ids=storage.Counter()

@pytest.fixture
def c():
    client=TestClient(app);r=client.post('/api/v1/auth/setup',json={'name':'Saba','username':'owner','password':PASS});assert r.status_code==201
    return client

def project(c,name='Atlas',color='blue'):
    r=c.post('/api/v1/projects',json={'name':name,'color':color});assert r.status_code==201,r.text
    return r.json()

def card(c,p=None,title='First task'):
    r=c.post('/api/v1/cards',json={'title':title,'goal':'A useful outcome','project_id':p['id'] if p else None});assert r.status_code==201,r.text
    return r.json()

def brief(c,p,title='Brief'):
    r=c.post('/api/v1/prds',json={'title':title,'content':CONTENT,'project_id':p['id']});assert r.status_code==201,r.text
    return r.json()

def preview(c,p):
    r=c.post('/api/v1/projects/'+p['id']+'/deletion-preview',json={});assert r.status_code==200,r.text
    return r.json()

def confirm(c,d,name=None):
    return c.post('/api/v1/projects/deletions/'+d['id']+'/confirm',json={'approve':True,'confirm_name':name if name is not None else d['project']['name']})

def test_project_create_rename_and_colors(c):
    p=project(c);assert c.get('/api/v1/projects').json()[0]['color']=='blue'
    updated=c.put('/api/v1/projects/'+p['id'],json={'name':'Atlas launch','color':'pink'});assert updated.status_code==200
    assert updated.json()['name']=='Atlas launch'
    assert c.post('/api/v1/projects',json={'name':'ATLAS LAUNCH','color':'blue'}).status_code==409
    assert c.post('/api/v1/projects',json={'name':'Other','color':'url(javascript:bad)'}).status_code==422

def test_existing_cards_remain_ungrouped_and_can_be_relabelled(c):
    a=card(c);p=project(c)
    assert a['project_id'] is None
    r=c.patch('/api/v1/cards/'+str(a['id']),json={'project_id':p['id']});assert r.status_code==200
    assert c.get('/api/v1/projects').json()[0]['card_count']==1
    assert c.patch('/api/v1/cards/'+str(a['id']),json={'project_id':None}).status_code==200
    assert c.get('/api/v1/cards').json()[0]['project_id'] is None

def test_unknown_project_rejected(c):
    r=c.post('/api/v1/cards',json={'title':'T','goal':'G','project_id':str(uuid4())});assert r.status_code==404
    assert c.post('/api/v1/prds',json={'title':'B','content':CONTENT,'project_id':str(uuid4())}).status_code==404

def test_card_delete_removes_comments_from_sqlite(c):
    a=card(c);assert c.post(f'/api/v1/cards/{a["id"]}/comments',json={'text':'This should disappear'}).status_code==201
    assert c.delete(f'/api/v1/cards/{a["id"]}').status_code==204
    assert not storage.cards and not storage.comments
    with storage.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM comments').fetchone()[0]==0
    assert c.get(f'/api/v1/cards/{a["id"]}').status_code==404

def test_deleting_prerequisite_removes_link(c):
    a = card(c, title="API")
    b = card(c, title="UI")

    with storage.transaction():
        storage.cards[b["id"]]["depends_on"] = [a["id"]]

    assert c.delete(f'/api/v1/cards/{a["id"]}').status_code == 204
    assert a["id"] not in storage.cards
    assert b["id"] in storage.cards
    assert storage.cards[b["id"]]["depends_on"] == []

def test_whole_project_cascade_preserves_other_projects(c):
    p=project(c);other=project(c,'Orchid','pink');a=card(c,p);keep=card(c,other);ungrouped=card(c,title='Ungrouped task');d=brief(c,p)
    c.post(f'/api/v1/cards/{a["id"]}/comments',json={'text':'remove this'});c.post(f'/api/v1/cards/{keep["id"]}/comments',json={'text':'keep this'})
    # Internal prerequisites are all removed together, not blocked individually.
    b=card(c,p,'Dependent')
    with storage.transaction():storage.cards[b['id']]['depends_on']=[a['id']]
    old=c.put(f'/api/v1/prds/{d["id"]}',json={'title':'Revision 2','content':CONTENT+' Updated scope.','expected_revision':1,'project_id':p['id']});assert old.status_code==200
    v=preview(c,p);assert len(storage.cards)==4 and len(v['briefs'])==1
    assert confirm(c,v,'Wrong name').status_code==422 and len(storage.cards)==4
    result=confirm(c,v);assert result.status_code==200,result.text
    assert set(storage.cards)=={keep['id'],ungrouped['id']}
    assert list(storage.projects)==[other['id']] and not storage.prds and len(storage.comments)==1
    with storage.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM prd_revisions WHERE prd_id=?',(d['id'],)).fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==1
    assert confirm(c,v).json()==result.json() # Idempotent receipt, no second deletion.
    assert storage.people and len(storage.comments)==1

def test_project_preview_changes_are_rejected(c):
    p=project(c);a=card(c,p);v=preview(c,p)
    c.post(f'/api/v1/cards/{a["id"]}/comments',json={'text':'new discussion'})
    assert confirm(c,v).status_code==409 and p['id'] in storage.projects

def test_other_project_changes_do_not_block_target_delete(c):
    p=project(c);q=project(c,'Other');a=card(c,p);b=card(c,q);v=preview(c,p)
    c.patch(f'/api/v1/cards/{b["id"]}',json={'title':'Edited other task'})
    assert confirm(c,v).status_code==200 and b['id'] in storage.cards

def test_cross_project_dependency_blocks_preview(c):
    p=project(c);a=card(c,p);b=card(c)
    with storage.transaction():storage.cards[b['id']]['depends_on']=[a['id']]
    r=c.post(f'/api/v1/projects/{p["id"]}/deletion-preview',json={});assert r.status_code==409
    assert str(b['id']) in r.json()['detail']

def test_external_card_source_brief_blocks_preview(c):
    p=project(c);d=brief(c,p);a=card(c)
    with storage.transaction():storage.cards[a['id']]['source_prd_id']=d['id']
    assert c.post(f'/api/v1/projects/{p["id"]}/deletion-preview',json={}).status_code==409

def test_expired_preview_and_direct_delete_rejected(c):
    p=project(c);v=preview(c,p)
    storage.proposals[v['id']]['expires']=time.time()-1
    assert confirm(c,v).status_code==410
    assert c.delete(f'/api/v1/projects/{p["id"]}').status_code==405
    assert p['id'] in storage.projects

def test_no_cross_origin_or_unauthenticated_access(c):
    assert TestClient(app).get('/api/v1/projects').status_code==401
    assert c.post('/api/v1/projects',headers={'Origin':'https://other.example'},json={'name':'Bad'}).status_code==403

def member(c):
    person=c.post('/api/v1/people',json={'name':'Mina','skills':['Testing'],'responsibility':'QA'}).json()
    invite=c.post('/api/v1/auth/invitations',json={'person_id':person['id']}).json()
    m=TestClient(app);r=m.post('/api/v1/auth/accept-invite',json={'username':'mina','password':PASS,'token':invite['token']});assert r.status_code==201,r.text
    return m

def test_project_permissions_and_preview_account_scope(c):
    p=project(c);v=preview(c,p);m=member(c)
    assert m.post(f'/api/v1/projects/{p["id"]}/deletion-preview',json={}).status_code==403
    assert m.put(f'/api/v1/projects/{p["id"]}',json={'name':'Hacked','color':'red'}).status_code==403
    assert confirm(m,v).status_code==404
    own=project(m,'Member project');assert confirm(m,preview(m,own)).status_code==200

def test_chat_drafts_inherit_server_selected_project(c,monkeypatch):
    p=project(c);q=project(c,'Other');conversation=str(uuid4())
    raw={'cards':[{'title':'First task','goal':'Useful','acceptance_criteria':['Testable result'],'out_of_scope':'Extra scope','project_id':q['id']}]}
    monkeypatch.setattr(assistant,'ask_model',lambda *a,**kw:{'model':'fake','message':json.dumps(raw)})
    r=c.post('/api/v1/assistant/chat',json={'conversation_id':conversation,'mode':'plan','project_id':p['id'],'messages':[{'role':'user','content':'Plan a first task'}]});assert r.status_code==200,r.text
    token=r.json()['proposal']['id'];assert not storage.cards
    out=c.post(f'/api/v1/assistant/proposals/{token}/confirm',json={'conversation_id':conversation,'approve':True});assert out.status_code==200,out.text
    assert out.json()['cards'][0]['project_id']==p['id']

def test_prd_drafts_inherit_brief_project(c,monkeypatch):
    p=project(c);d=brief(c,p);conversation=str(uuid4())
    def fake(messages,response_model):return {'model':'fake','parsed':response_model.model_validate({'cards':[{'key':'task','title':'A new task','goal':'Useful','acceptance_criteria':['Testable'],'out_of_scope':'Extras','depends_on':[]}]})}
    monkeypatch.setattr(prds,'ask_structured',fake)
    r=c.post(f'/api/v1/prds/{d["id"]}/breakdown',json={'conversation_id':conversation,'expected_revision':1,'messages':[]});assert r.status_code==200,r.text
    out=c.post(f'/api/v1/assistant/proposals/{r.json()["proposal"]["id"]}/confirm',json={'conversation_id':conversation,'approve':True});assert out.status_code==200,out.text
    assert out.json()['cards'][0]['project_id']==p['id']

def test_deleted_project_blocks_old_creation_preview(c,monkeypatch):
    p=project(c);conversation=str(uuid4())
    monkeypatch.setattr(assistant,'ask_model',lambda *a,**kw:{'model':'fake','message':json.dumps({'cards':[{'title':'Task','goal':'G','acceptance_criteria':['Test'],'out_of_scope':''}]})})
    r=c.post('/api/v1/assistant/chat',json={'conversation_id':conversation,'mode':'plan','project_id':p['id'],'messages':[{'role':'user','content':'Create task'}]});token=r.json()['proposal']['id']
    assert confirm(c,preview(c,p)).status_code==200
    assert c.post(f'/api/v1/assistant/proposals/{token}/confirm',json={'conversation_id':conversation,'approve':True}).status_code==404
    assert not storage.cards

def test_deleted_card_clears_cached_project_delete_preview(c):
    p=project(c);a=card(c,p);v=preview(c,p)
    assert c.delete(f'/api/v1/cards/{a["id"]}').status_code==204
    assert v['id'] not in storage.proposals

def test_atomic_deletion_rolls_back_on_flush_failure(c,monkeypatch):
    p=project(c);a=card(c,p);d=brief(c,p);v=preview(c,p)
    before=deepcopy((storage.projects,storage.cards,storage.prds))
    real_flush=storage.flush
    def fail(db):
        real_flush(db)
        raise RuntimeError('Simulated disk write failure after SQL changes')
    with monkeypatch.context() as m:
        m.setattr(storage,'flush',fail)
        with pytest.raises(RuntimeError):confirm(c,v)
    assert (storage.projects,storage.cards,storage.prds)==before
    with storage.connection() as db:assert db.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==1

def test_restart_preserves_labels_and_deletions(c):
    p=project(c);q=project(c,'Keep');a=card(c,p);keep=card(c,q)
    assert confirm(c,preview(c,p)).status_code==200
    script='from app import storage; import json; print(json.dumps({"projects":list(storage.projects),"cards":list(storage.cards),"label":list(storage.cards.values())[0]["project_id"]}))'
    out=subprocess.check_output([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'ZERO_MAGIC_DB':str(storage.DB_PATH)},text=True)
    result=json.loads(out);assert result=={'projects':[q['id']],'cards':[keep['id']],'label':q['id']}


def test_discussion_model_context_is_project_scoped(c,monkeypatch):
    p=project(c);q=project(c,'Other');a=card(c,p,'Target project task');card(c,q,'Do not mix into target plan');card(c,title='Ungrouped idea')
    captured=[]
    def answer(messages,**kw):
        captured.append(json.loads(messages[1]['content'].split('\n',1)[1]))
        return {'model':'fake','message':'Discuss only the selected project.'}
    monkeypatch.setattr(assistant,'ask_model',answer)
    r=c.post('/api/v1/assistant/chat',json={'conversation_id':str(uuid4()),'project_id':p['id'],'messages':[{'role':'user','content':'What is next?'}]})
    assert r.status_code==200,r.text
    assert [x['id'] for x in captured[0]['cards']]==[a['id']]
    assert captured[0]['selected_project']['name']==p['name']


def test_cancel_revokes_deletion_preview(c):
    p=project(c);a=card(c,p);v=preview(c,p)
    assert c.post(f'/api/v1/projects/deletions/{v["id"]}/cancel',json={}).status_code==200
    assert confirm(c,v).status_code==404 and a['id'] in storage.cards
