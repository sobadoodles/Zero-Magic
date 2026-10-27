"""Uses a throwaway SQLite DB, synthetic documents, and no AI/network calls."""
import base64
import io
import json
import subprocess
import zipfile
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app import storage, documents
from app.document_worker import extract, DocumentError
from app.main import app

TEXT = 'Build a shared team board. Members can add cards, discuss requirements, and approve a small first-release plan. Keep email and billing out of scope.'


def pdf(text=TEXT, pages=1, password=None):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(('BT /F1 12 Tf 40 740 Td ('+text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')+') Tj ET').encode('latin-1'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    result=io.BytesIO();writer.write(result);return result.getvalue()


def docx(text=TEXT, extra=None):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml',f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table requirement</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        if extra:
            for name,content in extra.items():z.writestr(name,content)
    return result.getvalue()


@pytest.fixture(autouse=True)
def reset():
    with storage.lock,storage.connection() as db:
        for table in ('sessions','invitations','users','login_attempts','prd_generation_requests','prd_revisions','prds','proposals','comments','cards','people','counters'):
            db.execute(f'DELETE FROM {table}')
    for records in (storage.cards,storage.people,storage.comments,storage.proposals,storage.prds):records.clear()
    storage.card_ids=storage.Counter();storage.person_ids=storage.Counter();storage.comment_ids=storage.Counter()
    documents.attempts.clear()


@pytest.fixture
def client():
    c=TestClient(app)
    r=c.post('/api/v1/auth/setup',json={'name':'Saba','username':'owner','password':'test-passphrase-12345'})
    assert r.status_code==201
    return c


def upload(c, data=None, name='brief.pdf'):
    return c.post('/api/v1/documents/extract',json={'filename':name,'content_base64':base64.b64encode(pdf() if data is None else data).decode()})


def test_pdf_review_only(client):
    r=upload(client);assert r.status_code==200,r.text
    assert '[Page 1]' in r.json()['text'] and 'shared team board' in r.json()['text']
    assert r.json()['page_count']==1 and r.json()['source_name']=='brief.pdf'
    assert not storage.cards and not storage.prds and not storage.proposals
    assert client.get('/api/v1/prds').json()==[]


def test_docx_review_and_save_explicitly(client):
    r=upload(client,docx(),'requirements.DOCX');assert r.status_code==200,r.text
    text=r.json()['text'];assert TEXT in text and 'Table requirement' in text
    assert r.json()['page_count'] is None and not storage.prds
    save=client.post('/api/v1/prds',json={'title':'Imported brief','content':text,'source_name':'requirements.DOCX'})
    assert save.status_code==201 and save.json()['content']==text
    assert not storage.cards


@pytest.mark.parametrize('data,name,code,fragment',[
    (b'not a PDF','.pdf',422,'valid PDF'),
    (b'%PDF- broken','.pdf',422,'could not be read'),
    (pdf(None),'.pdf',422,'OCR'),
    (pdf(password='private'),'.pdf',422,'Password-protected'),
    (pdf(None,pages=51),'.pdf',422,'50 pages'),
    (docx(),'.doc',415,'Old .doc'),
    (b'not a zip','.docx',422,'valid .docx'),
    (docx(extra={'word/vbaProject.bin':b'dummy'}),'.docx',422,'Macro-enabled'),
    (b'abc','.html',415,'Use a .pdf'),
    (b'', '.pdf',422,'filename and base64'),
])
def test_bad_files(client,data,name,code,fragment):
    r=upload(client,data,'brief'+name);assert r.status_code==code,r.text
    assert fragment.lower() in r.json()['detail'].lower()
    assert not storage.prds and not storage.cards


def test_short_text_is_editable(client):
    r=upload(client,pdf('A short idea.'));assert r.status_code==200
    assert 'short idea' in r.json()['text']


def test_long_text_never_truncated(client):
    r=upload(client,docx('requirements '*2000),'large.docx')
    assert r.status_code==422 and 'Nothing was truncated' in r.json()['detail']


def test_entities_rejected(client):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('word/document.xml','<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    assert upload(client,data.getvalue(),'entities.docx').status_code==422


def test_deleted_word_text_ignored():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Current scope</w:t></w:r><w:del><w:r><w:t>OLD SECRET SCOPE</w:t></w:r></w:del></w:p></w:body></w:document>')
    assert extract(data.getvalue(),'.docx')['text']=='Current scope'


def test_zip_expansion_limit(client):
    r=upload(client,docx(extra={'large.bin':b'0'*(21*1024*1024)}),'bomb.docx')
    assert r.status_code==422 and 'safe size' in r.json()['detail']


def test_auth_required():
    assert upload(TestClient(app)).status_code==401


def test_cross_origin_blocked(client):
    r=client.post('/api/v1/documents/extract',headers={'Origin':'https://other.example'},json={})
    assert r.status_code==403


def test_wrong_content_type(client):
    assert client.post('/api/v1/documents/extract',content=b'x').status_code==415


def test_invalid_base64(client):
    r=client.post('/api/v1/documents/extract',json={'filename':'x.pdf','content_base64':'###'})
    assert r.status_code==422 and 'encoding' in r.json()['detail']


def test_filename_path_rejected(client):
    assert upload(client,name='../../brief.pdf').status_code==422


def test_body_limit(client):
    r=client.post('/api/v1/documents/extract',content=b'x'*(documents.MAX_BODY+1),headers={'Content-Type':'application/json'})
    assert r.status_code==413


def test_rate_limit(client):
    for _ in range(3):assert upload(client).status_code==200
    assert upload(client).status_code==429


def test_subprocess_timeout(client,monkeypatch):
    def fail(*a,**kw):raise subprocess.TimeoutExpired('worker',12)
    monkeypatch.setattr(documents.subprocess,'run',fail)
    r=upload(client);assert r.status_code==422 and 'timed out' in r.json()['detail']
    # Semaphore released even after timeout.
    assert documents.slots.acquire(blocking=False);documents.slots.release()


def test_busy_worker(client):
    assert documents.slots.acquire(False) and documents.slots.acquire(False)
    try:assert upload(client).status_code==429
    finally:documents.slots.release();documents.slots.release()


def test_worker_does_not_inherit_api_key(client,monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','test-secret-not-for-child')
    def fake_run(command,**kwargs):
        assert 'GROQ_API_KEY' not in kwargs['env']
        assert '-E' in command and '-P' in command
        return subprocess.CompletedProcess(command,0,json.dumps({'ok':True,'text':TEXT,'page_count':1,'warnings':[]}).encode())
    monkeypatch.setattr(documents.subprocess,'run',fake_run)
    assert upload(client).status_code==200
