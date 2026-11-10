"""Week 5: the card stage machine as a fully tested, injectable domain module.

Matrix: every (from, to) pair is asserted legal or refused — no surprises.
Also pins the EXACT public 409 messages and proves the domain module needs no
storage/HTTP: policies are injected callables.
"""
import pytest
from fastapi.testclient import TestClient

from app import storage
from app.domain.card_state import (ALLOWED_TRANSITIONS, STAGES, blocked_prerequisites,
                                   legal_next, transition_error)
from app.main import app

# The one specification, written out as pairs -> allowed?
LEGAL_PAIRS = {
    ("Spec", "Ready"),
    ("Ready", "Building"),
    ("Building", "Checks"),
    ("Checks", "Validation"), ("Checks", "Building"),
    ("Validation", "Done"), ("Validation", "Building"),
}


@pytest.fixture(autouse=True)
def reset():
    with storage.lock, storage.connection() as db:
        for table in ('sessions', 'invitations', 'users', 'login_attempts', 'proposals',
                      'comments', 'cards', 'people', 'counters'):
            db.execute(f'DELETE FROM {table}')
    for records in (storage.cards, storage.people, storage.comments, storage.proposals):
        records.clear()
    storage.card_ids = storage.Counter()
    storage.person_ids = storage.Counter()
    storage.comment_ids = storage.Counter()


def test_domain_module_is_pure_no_io_imports():
    import inspect
    import re as _re
    source = inspect.getsource(__import__('app.domain.card_state', fromlist=['card_state']))
    imports = [line.strip() for line in source.splitlines()
               if _re.match(r'\s*(import|from)\s', line)]
    assert imports, "module should at least import typing"
    assert not any(_re.search(r'\b(app\.|fastapi|starlette|storage|httpx|sqlite3)\b', line)
                   for line in imports), f"domain layer must stay I/O-free: {imports}"


def test_transition_matrix_is_exhaustive():
    for current in STAGES:
        for target in STAGES:
            card = {"stage": current}
            refusal = transition_error(card, target)
            if (current, target) in LEGAL_PAIRS:
                assert refusal is None, f"{current}->{target} should be legal"
            else:
                assert refusal is not None, f"{current}->{target} must be refused"
                assert refusal[0] == 409
                assert refusal[1] == f"Cannot move card from {current} to {target}"


def test_done_is_terminal_from_every_target():
    for target in STAGES:
        assert transition_error({"stage": "Done"}, target) is not None or target == "Done"


def test_legal_next_matches_matrix_and_is_sorted():
    for stage in STAGES:
        assert legal_next(stage) == sorted(t for s, t in LEGAL_PAIRS if s == stage)
    assert legal_next("Done") == []


def test_unknown_current_stage_is_refused_not_crashed():
    status, message = transition_error({"stage": "Banana"}, "Ready")
    assert status == 409 and "Banana" in message


# --- prerequisite policy, injected ---------------------------------------------------

def test_blocked_prerequisites_with_pure_injected_policy():
    card = {"stage": "Ready", "depends_on": [7, 8, 9]}
    stages = {7: "Done", 8: "Validation", 9: None}  # 9 no longer readable
    assert blocked_prerequisites(card, stages.get) == [8, 9]
    assert blocked_prerequisites(card, lambda _id: "Done") == []
    assert blocked_prerequisites({"stage": "Ready"}, lambda _id: None) == []


def test_building_guard_blocks_then_allows_through_the_domain():
    card = {"stage": "Ready", "depends_on": [42]}
    blocked = transition_error(card, "Building", stage_of=lambda _id: "Spec")
    assert blocked == (409, "Finish prerequisite cards first: #42")
    assert transition_error(card, "Building", stage_of=lambda _id: "Done") is None
    # guards apply ONLY to Building; Ready->? others untouched
    assert transition_error(card, "Checks") is not None  # Ready->Checks illegal anyway


# --- endpoint integration keeps byte-exact public messages ------------------------

def owner():
    c = TestClient(app)
    assert c.post('/api/v1/auth/setup', json={'username': 'owner', 'password': 'test-passphrase-12345',
                                              'name': 'Saba'}).status_code == 201
    return c


def test_api_illegal_and_guarded_moves_keep_their_409_wording():
    c = owner()
    card = c.post('/api/v1/cards', json={'title': 'T', 'goal': 'G'}).json()
    jump = c.patch(f"/api/v1/cards/{card['id']}/stage", json={'stage': 'Validation'})
    assert jump.status_code == 409
    assert jump.json()['detail'] == 'Cannot move card from Spec to Validation'

    other = c.post('/api/v1/cards', json={'title': 'Dep', 'goal': 'G'}).json()
    c.patch(f"/api/v1/cards/{other['id']}/stage", json={'stage': 'Ready'})
    c.patch(f"/api/v1/cards/{other['id']}/stage", json={'stage': 'Building'})
    c.patch(f"/api/v1/cards/{other['id']}/stage", json={'stage': 'Checks'})
    with storage.transaction():
        storage.cards[other['id']]['depends_on'] = [card['id']]
    # Checks -> Building is a legal transition, but the prerequisite guard still applies.
    blocked = c.patch(f"/api/v1/cards/{other['id']}/stage", json={'stage': 'Building'})
    assert blocked.status_code == 409
    assert blocked.json()['detail'] == f"Finish prerequisite cards first: #{card['id']}"

    c.patch(f"/api/v1/cards/{card['id']}/stage", json={'stage': 'Ready'})
    for stage in ('Building', 'Checks', 'Validation', 'Done'):
        assert c.patch(f"/api/v1/cards/{card['id']}/stage", json={'stage': stage}).status_code == 200
    assert c.patch(f"/api/v1/cards/{other['id']}/stage", json={'stage': 'Building'}).status_code == 200
