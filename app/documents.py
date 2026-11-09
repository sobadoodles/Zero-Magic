"""Authenticated, extraction-only import. No saved files, model calls or DB writes."""
import base64
import binascii
import json
import os
import subprocess
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import BoundedSemaphore, Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.auth import require_user

router = APIRouter(prefix='/api/v1/documents', tags=['Document import'])
MAX_FILE = 2 * 1024 * 1024
MAX_BODY = 2_800_000
MAX_WORKER_OUTPUT = 400_000
slots = BoundedSemaphore(2)
rate_lock = Lock()
attempts = defaultdict(deque)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=150)
    content_base64: str = Field(min_length=1, max_length=2_796_204)


def reserve(user_id):
    now = time.monotonic()
    with rate_lock:
        # Small process-local throttle, not an authentication/security boundary.
        for key in list(attempts):
            while attempts[key] and attempts[key][0] <= now - 60:
                attempts[key].popleft()
            if not attempts[key]:
                del attempts[key]
        if len(attempts[user_id]) >= 3:
            raise HTTPException(429, 'Import limit reached. Wait a minute before trying again.')
        attempts[user_id].append(now)


def parse_document(data, suffix, structured=False):
    if not slots.acquire(blocking=False):
        raise HTTPException(429, 'Document import is busy. Try again shortly.')
    try:
        try:
            worker = Path(__file__).with_name('document_worker.py')
            command = [sys.executable, '-E', '-P', str(worker), suffix]
            if structured:
                command.append('--structure')
            result = subprocess.run(command, input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=False,
                                    env={k:v for k,v in os.environ.items() if k in {
                                        'PATH','SystemRoot','WINDIR','HOME','USERPROFILE','TEMP','TMP',
                                        'LOCALAPPDATA','APPDATA','LD_LIBRARY_PATH'}})
        except subprocess.TimeoutExpired:
            raise HTTPException(422, 'Document extraction timed out. Export a simpler document or paste its text.')
        if result.returncode or len(result.stdout) > MAX_WORKER_OUTPUT:
            raise HTTPException(422, 'The document exceeded extraction limits. Export a simpler document or paste its text.')
        try:
            parsed = json.loads(result.stdout.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise HTTPException(422, 'The document could not be read safely. Try a simpler export.')
        if not parsed.get('ok'):
            raise HTTPException(422, parsed.get('error', 'Document extraction failed.'))
        parsed.pop('ok', None)
        return parsed
    finally:
        slots.release()


async def read_upload(request: Request, user_id):
    """Shared validation for both extraction routes. Returns (filename, suffix, bytes)."""
    reserve(user_id)
    size = request.headers.get('content-length')
    if size and size.isdecimal() and int(size) > MAX_BODY:
        raise HTTPException(413, 'Choose a document no larger than 2 MB.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, 'Choose a document no larger than 2 MB.')
        body.extend(chunk)
    try:
        payload = ImportRequest.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, 'Send a filename and base64 document content only.')
    filename = payload.filename
    if '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename):
        raise HTTPException(422, 'Use a filename without paths or control characters.')
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.pdf', '.docx'):
        raise HTTPException(415, 'Use a .pdf or .docx file. Old .doc files are not supported.')
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'The uploaded document encoding is invalid. Choose the file again.')
    if not data or len(data) > MAX_FILE:
        raise HTTPException(413, 'Choose a non-empty document no larger than 2 MB.')
    return filename, suffix, data


@router.post('/extract')
async def extract_document(request: Request, user=Depends(require_user)):
    filename, suffix, data = await read_upload(request, user['id'])
    result = await run_in_threadpool(parse_document, data, suffix)
    return {'source_name': filename, 'format': suffix[1:], **result}


@router.post('/structure')
async def structure_document(request: Request, user=Depends(require_user)):
    """Extract WITH page/heading structure and split into reviewable chunks.

    Like /extract, this is read-only: nothing is saved and no model is called.
    The client reviews the returned chunks, then explicitly saves them to the
    knowledge library through /api/v1/knowledge.
    """
    from app.document_chunks import chunk_document

    filename, suffix, data = await read_upload(request, user['id'])
    result = await run_in_threadpool(parse_document, data, suffix, True)
    pages = result.pop('pages', [])
    chunks = chunk_document(filename, {'pages': pages})
    return {
        'source_name': filename,
        'format': suffix[1:],
        'page_count': result.get('page_count'),
        'warnings': result.get('warnings', []),
        'chunks': [{'page': c['page'], 'heading': c['heading'], 'text': c['text']} for c in chunks],
        'chunk_count': len(chunks),
        'total_characters': sum(len(c['text']) for c in chunks),
    }
