"""Board API tests: attachment with a real ingest status machine, failure persistence,
retry, board listing/scoped ask. Parsing runs through the real bounded worker."""
import base64
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import documents, knowledge, storage
from app.main import app

PASS = 'test-passphrase-12345'


def pdf(text='Reminder rule: send one day before the due date at nine.'):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject(
        {NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    safe = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 40 740 Td ({safe}) Tj ET'.encode('latin-1'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture(autouse=True)
def reset():
    with storage.lock, storage.connection() as db:
        for table in ('sessions', 'invitations', 'users', 'login_attempts',
                      'prd_generation_requests', 'prd_revisions', 'prds', 'proposals',
                      'comments', 'cards', 'people', 'counters', 'projects',
                      'doc_files', 'doc_chunks', 'doc_vectors'):
            db.execute(f'DELETE FROM {table}')
    for records in (storage.cards, storage.people, storage.comments, storage.proposals,
                    storage.prds, storage.projects, storage.doc_files, storage.doc_chunks):
        records.clear()
    storage.card_ids = storage.Counter()
    storage.person_ids = storage.Counter()
    storage.comment_ids = storage.Counter()
    documents.attempts.clear()
    knowledge._embed_model = None


@pytest.fixture
def client():
    c = TestClient(app)
    r = c.post('/api/v1/auth/setup', json={'name': 'Saba', 'username': 'owner', 'password': PASS})
    assert r.status_code == 201
    return c


def board(client, name='Atlas', color='blue'):
    r = client.post('/api/v1/projects', json={'name': name, 'color': color})
    assert r.status_code == 201, r.text
    return r.json()


def upload(c, bid, data=None, name='atlas.pdf'):
    return c.post(f'/api/v1/boards/{bid}/documents', json={
        'filename': name,
        'content_base64': base64.b64encode(pdf() if data is None else data).decode()})


def test_boards_require_signin():
    anon = TestClient(app)
    assert anon.get('/api/v1/boards').status_code == 401
    assert anon.post(f'/api/v1/boards/{uuid4()}/ask', json={'question': 'x'}).status_code == 401


def test_list_boards_shows_counts(client):
    p = board(client, 'Atlas')
    client.post('/api/v1/cards', json={'title': 'T', 'goal': 'G', 'project_id': p['id']})
    listing = client.get('/api/v1/boards').json()['boards']
    assert listing[0]['name'] == 'Atlas' and listing[0]['color'] == 'blue'
    assert listing[0]['card_count'] == 1 and listing[0]['document_count'] == 0
    assert listing[0]['documents_by_status'] == {'pending': 0, 'processing': 0, 'ready': 0, 'failed': 0}


def test_ingest_reaches_ready_with_passages(client):
    p = board(client)
    response = upload(client, p['id'])
    assert response.status_code == 201, response.text
    document = response.json()['document']
    assert document['status'] == 'ready' and document['attempts'] == 1 and document['error'] is None
    assert document['chunk_count'] >= 1 and document['page_count'] == 1
    assert response.json()['board']['name'] == 'Atlas'
    keys = [key for key in storage.doc_chunks if storage.doc_chunks[key]['source'] == 'atlas.pdf']
    assert len(keys) == document['chunk_count']
    listed = client.get(f"/api/v1/boards/{p['id']}/documents").json()['documents']
    assert listed[0]['status'] == 'ready' and listed[0]['project_id'] == p['id']


def test_processing_status_is_committed_before_parsing(client, monkeypatch):
    p = board(client)
    seen = {}
    real_parse = documents.parse_document

    def spy(data, suffix, structured=False):
        seen['status'] = storage.doc_files['atlas.pdf']['status']
        return real_parse(data, suffix, structured)
    monkeypatch.setattr(documents, 'parse_document', spy)
    assert upload(client, p['id']).status_code == 201
    assert seen['status'] == 'processing'  # pending->processing was really committed first


def test_failed_ingest_persists_reason_and_is_not_retrievable(client):
    p = board(client)
    broken = TestClient(app)
    broken.cookies.update(client.cookies)
    response = broken.post(f'/api/v1/boards/{p["id"]}/documents',
                           json={'filename': 'broken.pdf', 'content_base64': '###not-base64###'})
    assert response.status_code == 422
    record = storage.doc_files['broken.pdf']
    assert record['status'] == 'failed' and 'encoding' in record['error'].lower()
    # failed documents stay out of every reader path
    with storage.lock:
        assert 'broken.pdf' not in knowledge.allowed_sources(p['id'])
        assert 'broken.pdf' not in knowledge.allowed_sources(None)
    assert client.post('/api/v1/knowledge/search', json={'query': 'anything'}).json()['results'] == []


def test_failed_document_can_be_retried(client):
    p = board(client)
    assert upload(client, p['id'], data=b'not a pdf').status_code == 422
    assert storage.doc_files['atlas.pdf']['status'] == 'failed'
    retry = upload(client, p['id'])  # same name, now valid bytes
    assert retry.status_code == 201, retry.text
    document = retry.json()['document']
    assert document['status'] == 'ready' and document['attempts'] == 2 and document['error'] is None


def test_ready_document_cannot_be_reuploaded(client):
    p = board(client)
    assert upload(client, p['id']).status_code == 201
    again = upload(client, p['id'])
    assert again.status_code == 409 and 'review-and-replace' in again.json()['detail']


def test_ingest_validation_before_any_record(client):
    p = board(client)
    assert upload(client, p['id'], name='../evil.pdf').status_code == 422
    assert upload(client, p['id'], name='notes.txt').status_code == 415
    assert upload(client, str(uuid4()), name='ok.pdf').status_code == 404
    assert not storage.doc_files  # rejected uploads never created records


def test_board_ask_returns_board_named_cited_answer(client, monkeypatch):
    p = board(client)
    assert upload(client, p['id']).status_code == 201

    def fake(messages, response_model):
        return {'model': 'sim', 'parsed': response_model.model_validate(
            {'found': True, 'answer': 'One day before at nine [K1].', 'citations': ['K1']})}
    monkeypatch.setattr('app.document_qa.ask_structured', fake)
    response = client.post(f"/api/v1/boards/{p['id']}/ask", json={'question': 'when is the reminder'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['board']['name'] == 'Atlas' and body['passages_consulted'] >= 1
    assert body['citations'][0]['document'] == 'atlas.pdf'
    assert body['model'] == 'sim'


def test_board_ask_not_found_without_any_documents(client, monkeypatch):
    p = board(client)
    monkeypatch.setattr('app.document_qa.ask_structured', lambda *a, **k: pytest.fail('no model needed'))
    response = client.post(f"/api/v1/boards/{p['id']}/ask", json={'question': 'anything at all'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['found'] is False and body['model'] == 'application' and body['citations'] == []


def test_projects_ask_alias_and_boards_ask_match_contract(client, monkeypatch):
    p = board(client)
    assert upload(client, p['id']).status_code == 201

    def fake(messages, response_model):
        return {'model': 'sim', 'parsed': response_model.model_validate(
            {'found': True, 'answer': 'One day before [K1].', 'citations': ['K1']})}
    monkeypatch.setattr('app.document_qa.ask_structured', fake)
    via_project = client.post(f"/api/v1/projects/{p['id']}/ask", json={'question': 'reminder'}).json()
    via_board = client.post(f"/api/v1/boards/{p['id']}/ask", json={'question': 'reminder'}).json()
    for key in ('found', 'answer', 'citations', 'model', 'passages_consulted', 'mode'):
        assert via_project[key] == via_board[key]
    assert via_project['project']['id'] == via_board['board']['id'] == p['id']


def test_interrupted_ingest_recovers_on_import(client):
    p = board(client)
    with storage.transaction():
        storage.doc_files['ghost.pdf'] = {'source_name': 'ghost.pdf', 'format': 'pdf',
                                          'project_id': p['id'], 'status': 'processing',
                                          'attempts': 1, 'error': None, 'page_count': None,
                                          'chunk_count': 0, 'characters': 0, 'ingested_by': 1,
                                          'ingested_at': 'x', 'processed_at': None}
    knowledge._recover_interrupted_ingests()
    record = storage.doc_files['ghost.pdf']
    assert record['status'] == 'failed' and 'restart' in record['error'].lower()
    with storage.connection() as db:  # the sweep was persisted, not just in memory
        stored = json.loads(db.execute("SELECT data FROM doc_files WHERE id='ghost.pdf'").fetchone()[0])
    assert stored['status'] == 'failed'
