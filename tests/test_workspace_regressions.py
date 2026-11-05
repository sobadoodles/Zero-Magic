"""Contract checks for existing cards, comments, and stage rules."""
from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def clear_cards():
    storage.cards.clear()
    storage.comments.clear()
    storage.card_ids=count(1)
    storage.comment_ids=count(1)


def create():
    result=client.post('/api/v1/cards',json={'title':'  Task  ','goal':'  Learn  '})
    assert result.status_code==201
    return result.json()


def test_crud_and_partial_update_contract():
    card=create()
    assert card['title']=='Task'
    assert card['goal']=='Learn'
    assert client.get('/api/v1/cards').json()[0]['comment_count']==0
    updated=client.patch('/api/v1/cards/1',json={'title':'New title'})
    assert updated.status_code==200
    assert updated.json()['goal']=='Learn'
    assert client.patch('/api/v1/cards/1',json={'title':None}).status_code==422
    assert client.get('/api/v1/cards/1').json()['title']=='New title'
    assert client.delete('/api/v1/cards/1').status_code==204
    assert client.get('/api/v1/cards/1').status_code==404


@pytest.mark.parametrize('payload',[{'title':'   ','goal':'Learn'},{'title':'Task'},{'title':'Task','goal':'Learn','stage':'Done'}])
def test_bad_create_payload_rejected(payload):
    assert client.post('/api/v1/cards',json=payload).status_code==422
    assert storage.cards=={}


def test_stage_rules_still_enforced():
    create()
    assert client.patch('/api/v1/cards/1/stage',json={'stage':'Done'}).status_code==409
    assert client.patch('/api/v1/cards/1/stage',json={'stage':'Unknown'}).status_code==422
    for stage in ['Ready','Building','Checks','Validation','Building','Checks','Validation','Done']:
        result=client.patch('/api/v1/cards/1/stage',json={'stage':stage})
        assert result.status_code==200
        assert result.json()['stage']==stage
    assert client.patch('/api/v1/cards/1/stage',json={'stage':'Building'}).status_code==409


def test_legacy_comments_and_cascade_delete():
    create()
    result=client.post('/api/v1/cards/1/comments',json={'author':'  Intern  ','text':'  Hello  '})
    assert result.status_code==201
    assert result.json()['author']=='Intern'
    assert result.json()['text']=='Hello'
    assert client.get('/api/v1/cards/1/comments').json()==[result.json()]
    client.delete('/api/v1/cards/1')
    assert storage.comments=={}
    assert client.get('/api/v1/cards/1/comments').status_code==404
