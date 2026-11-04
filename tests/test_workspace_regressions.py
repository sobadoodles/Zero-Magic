"""Contract checks for existing cards, comments, and stage rules."""
from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app

client=TestClient(app)


@pytest.fixture(autouse=True)
def signed_in_workspace():
    with storage.lock, storage.connection() as db:
        for table in (
            "sessions", "invitations", "users", "login_attempts",
            "prd_generation_requests", "prd_revisions", "prds",
            "proposals", "comments", "cards", "people", "projects",
            "counters",
        ):
            db.execute(f"DELETE FROM {table}")

        for records in (
            storage.cards, storage.people, storage.comments,
            storage.proposals, storage.prds, storage.projects,
        ):
            records.clear()

        storage.card_ids = storage.Counter(1)
        storage.person_ids = storage.Counter(1)
        storage.comment_ids = storage.Counter(1)

    client.cookies.clear()
    setup = client.post(
        "/api/v1/auth/setup",
        json={
            "name": "Test Owner",
            "username": "testowner",
            "password": "test-passphrase-12345",
        },
    )
    assert setup.status_code == 201, setup.text
    yield
    client.cookies.clear()

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
    card = create()
    card_id = card["id"]

    # Simulate a historical comment imported before logins existed.
    with storage.transaction():
        legacy_id = next(storage.comment_ids)
        storage.comments[legacy_id] = {
            "id": legacy_id,
            "card_id": card_id,
            "author": "Intern",
            "author_id": None,
            "user_id": None,
            "created_at": None,
            "text": "Old comment",
        }

    url = f"/api/v1/cards/{card_id}/comments"

    # The old comment is still readable.
    listed = client.get(url)
    assert listed.status_code == 200
    assert listed.json()[0]["author"] == "Intern"

    # A new comment uses the signed-in identity.
    result = client.post(url, json={"text": "  Hello  "})
    assert result.status_code == 201, result.text
    assert result.json()["author"] == "Test Owner"
    assert result.json()["text"] == "Hello"
    assert len(client.get(url).json()) == 2

    # Deleting the card also deletes both comments.
    assert client.delete(f"/api/v1/cards/{card_id}").status_code == 204
    assert storage.comments == {}
    assert client.get(url).status_code == 404