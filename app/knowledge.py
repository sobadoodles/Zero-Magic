"""The shared document knowledge library: reviewed chunks live in SQLite.

Files themselves are never stored — only extracted, human-reviewed passages.
Search runs keyword-first; semantic vectors are optional, produced on demand by
the embed route. All routes require the existing local session login.
"""
import json
import re
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import storage
from app.auth import require_user
from app.document_chunks import normalize_for_search
from app.document_search import search_chunks
from app.schemas import NonBlankText
from app.semantic_search import MODEL_NAME, cosine_similarity

router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge library"],
                   dependencies=[Depends(require_user)])

MAX_DOCUMENTS = 60
MAX_TOTAL_CHUNKS = 3000
MAX_CHUNKS_PER_REQUEST = 800
MAX_CHUNK_TEXT = 2500
SOURCE_PATTERN = re.compile(r"^[^\x00-\x1f/\\]{1,150}$")

doc_files = storage.doc_files
doc_chunks = storage.doc_chunks
embed_lock = threading.Lock()
_embed_model = None


class ChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int | None = Field(default=None, ge=1, strict=True)
    heading: str | None = Field(default=None, max_length=200)
    text: NonBlankText = Field(max_length=MAX_CHUNK_TEXT)


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_name: str = Field(min_length=1, max_length=150)
    format: str = Field(default="pdf", pattern="^(pdf|docx)$")
    page_count: int | None = Field(default=None, ge=1, strict=True, le=50)
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    chunks: list[ChunkInput] = Field(min_length=1, max_length=800)


class LibrarySave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: list[DocumentInput] = Field(min_length=1, max_length=20)
    replace: bool = False


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: NonBlankText = Field(max_length=2000)
    limit: int = Field(default=5, ge=1, le=10, strict=True)
    mode: str = Field(default="keyword", pattern="^(keyword|semantic)$")
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")


class AskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: NonBlankText = Field(max_length=2000)
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    mode: str = Field(default="keyword", pattern="^(keyword|semantic)$")
    limit: int = Field(default=5, ge=1, le=8, strict=True)


class EmbedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False


def chunk_id(source, ordinal):
    return f"{source}::{ordinal:05d}"


def allowed_sources(project_id):
    """Passages attached to this project (board) plus unattached workspace-wide ones."""
    if project_id is None:
        return None
    return {name for name, record in doc_files.items()
            if record.get("project_id") in (None, project_id)}


def document_summary(record):
    return {k: v for k, v in record.items() if k != "internal"}


def list_documents():
    return [document_summary(doc_files[name]) for name in sorted(doc_files)]


@storage.synchronized
def get_document(source_name: str):
    record = doc_files.get(source_name)
    if record is None:
        raise HTTPException(404, "Document is not in the knowledge library.")
    passages = [
        doc_chunks[key]
        for key in sorted(doc_chunks)
        if doc_chunks[key]["source"] == source_name
    ]
    return {**document_summary(record), "chunks": passages}


@router.get("/{source_name}")
@storage.synchronized
def fetch_document(source_name: str):
    return get_document(source_name)


@router.post("", status_code=201)
@storage.synchronized
def save_library(payload: LibrarySave, user=Depends(require_user)):
    from app.projects import validate_project
    incoming = {}
    for document in payload.documents:
        name = document.source_name.strip()
        if not SOURCE_PATTERN.match(name) or name in incoming:
            raise HTTPException(422, "Use a plain filename without paths, once per document.")
        validate_project(document.project_id)
        incoming[name] = document

    reused = [name for name in incoming if name in doc_files]
    if reused and not payload.replace:
        raise HTTPException(409,
            "These documents are already in the library: "
            + ", ".join(sorted(reused))
            + ". Send replace=true only if you mean to rebuild their passages.")

    projected_total = len(doc_chunks) - sum(
        len([key for key in doc_chunks if doc_chunks[key]["source"] == name]) for name in reused
    ) + sum(len(document.chunks) for document in incoming.values())
    if len(doc_files) - len(reused) + len(incoming) > MAX_DOCUMENTS:
        raise HTTPException(409, f"The local library holds at most {MAX_DOCUMENTS} documents.")
    if projected_total > MAX_TOTAL_CHUNKS:
        raise HTTPException(409,
            f"This would exceed {MAX_TOTAL_CHUNKS} stored passages. Remove a document or import a smaller set.")

    now = datetime.now(timezone.utc).isoformat()
    saved = []
    for name, document in incoming.items():
        for key in [key for key in doc_chunks if doc_chunks[key]["source"] == name]:
            del doc_chunks[key]
        record = {
            "source_name": name,
            "format": document.format,
            "page_count": document.page_count,
            "project_id": document.project_id,
            "status": "ready",
            "chunk_count": len(document.chunks),
            "characters": sum(len(chunk.text) for chunk in document.chunks),
            "ingested_by": user["id"],
            "ingested_at": now,
        }
        doc_files[name] = record
        for ordinal, chunk in enumerate(document.chunks, 1):
            heading = (chunk.heading or "").strip() or None
            text = chunk.text
            doc_chunks[chunk_id(name, ordinal)] = {
                "id": chunk_id(name, ordinal),
                "source": name,
                "page": chunk.page,
                "heading": heading,
                "text": text,
                # The server always computes the normalized form; client copies are ignored.
                "text_normalized": normalize_for_search(text),
                "ordinal": ordinal,
            }
        saved.append(document_summary(record))
    return {"documents": saved,
            "total_chunks": len(doc_chunks),
            "message": f"Saved {len(saved)} document(s) with {sum(d['chunk_count'] for d in saved)} reviewed passages. No model was called."}


@router.get("")
@storage.synchronized
def get_library():
    with storage.connection() as db:
        vector_keys = {row[0] for row in db.execute("SELECT chunk_id FROM doc_vectors")}
    summaries = []
    for record in list_documents():
        name = record["source_name"]
        embedded = sum(1 for key in doc_chunks if doc_chunks[key]["source"] == name and key in vector_keys)
        summaries.append({**record, "embedded_chunks": embedded})
    return {"documents": summaries, "total_documents": len(summaries), "total_chunks": len(doc_chunks)}


@router.delete("/{source_name}")
@storage.synchronized
def remove_document(source_name: str, user=Depends(require_user)):
    record = doc_files.get(source_name)
    if record is None:
        raise HTTPException(404, "Document is not in the knowledge library.")
    if not user["is_admin"] and record["ingested_by"] != user["id"]:
        raise HTTPException(403, "Only the document's importer or the workspace owner can remove it.")
    del doc_files[source_name]
    removed = [key for key in doc_chunks if doc_chunks[key]["source"] == source_name]
    for key in removed:
        del doc_chunks[key]
    # flush() prunes the orphaned vectors from SQLite in the same transaction.
    return {"status": "removed", "source_name": source_name, "removed_chunks": len(removed)}


def keyword_results(query, limit, sources=None):
    from app.document_search import search_words

    ordered = [doc_chunks[key] for key in sorted(doc_chunks)
               if sources is None or doc_chunks[key]["source"] in sources]
    query_words = search_words(query)
    scored = []
    for chunk in search_chunks(ordered, query):
        scored.append({**chunk, "matches": len(query_words & search_words(chunk["text"]))})
    return scored[:limit]


def get_embed_model():
    """Lazy so imports and keyword tests never load fastembed (or download a model)."""
    global _embed_model
    if _embed_model is None:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise HTTPException(503, "Semantic search needs the fastembed package installed in .venv.")
        try:
            _embed_model = TextEmbedding(model_name=MODEL_NAME)
        except Exception:
            raise HTTPException(503, "The embedding model could not be loaded or downloaded. Check the connection and try again.")
    return _embed_model


def _load_vectors():
    with storage.connection() as db:
        rows = db.execute("SELECT chunk_id, data FROM doc_vectors").fetchall()
    vectors = {}
    for chunk_key, blob in rows:
        try:
            stored = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if stored.get("model") == MODEL_NAME and chunk_key in doc_chunks:
            vectors[chunk_key] = [float(value) for value in stored.get("vector", [])]
    return vectors


def semantic_results(query, limit, sources=None):
    vectors = _load_vectors()
    if not vectors:
        raise HTTPException(409, "No embedded passages yet. Use keyword search or run embedding first.")
    model = get_embed_model()
    try:
        query_vector = [float(value) for value in next(model.embed([query]))]
    except Exception:
        raise HTTPException(503, "The query could not be embedded. Try keyword mode.")
    ranked = []
    for chunk_key, vector in vectors.items():
        if len(vector) != len(query_vector):
            continue
        chunk = doc_chunks[chunk_key]
        if sources is not None and chunk["source"] not in sources:
            continue
        try:
            score = cosine_similarity(vector, query_vector)
        except ValueError:
            continue
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {**chunk, "similarity": round(score, 4)}
        for score, chunk in ranked[:limit]
    ]


def retrieve(query, limit=5, mode="keyword", project_id=None):
    """Shared by the API and the assistant. Keyword-first; returns labelled copies.

    project_id scopes to a board's attached documents plus workspace-wide passages.
    """
    from app.projects import validate_project
    with storage.lock:
        if project_id is not None:
            validate_project(project_id)
        sources = allowed_sources(project_id)
        if not doc_chunks:
            return []
        if mode == "semantic":
            return semantic_results(query, limit, sources)
        return keyword_results(query, limit, sources)


@router.post("/search")
def search_library(payload: SearchInput):
    results = retrieve(payload.query, payload.limit, payload.mode, payload.project_id)
    return {
        "query": payload.query,
        "mode": payload.mode,
        "results": [
            {"id": chunk["id"], "source": chunk["source"], "page": chunk["page"],
             "heading": chunk["heading"], "text": chunk["text"],
             **({"similarity": chunk["similarity"]} if "similarity" in chunk else {}),
             **({"matches": chunk["matches"]} if "matches" in chunk else {})}
            for chunk in results
        ],
    }


@router.post("/ask")
def ask_library(payload: AskInput):
    """Grounded question answering over the library (optionally board-scoped).

    Answers ONLY from retrieved passages, with document/page/quote citations, or a
    plain not-found statement. Provider/contract failures return 503 — never a guess.
    """
    from app.document_qa import answer_from_passages
    passages = retrieve(payload.question, payload.limit, payload.mode, payload.project_id)
    result = answer_from_passages(payload.question, passages)
    if "skipped" in result:
        raise HTTPException(503, result["skipped"])
    return {"question": payload.question, "project_id": payload.project_id, "mode": payload.mode,
            "passages_consulted": len(passages), **result}


class AttachInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")


@router.put("/{source_name}")
@storage.synchronized
def attach_document(source_name: str, payload: AttachInput, user=Depends(require_user)):
    from app.projects import validate_project
    record = doc_files.get(source_name)
    if record is None:
        raise HTTPException(404, "Document is not in the knowledge library.")
    if not user["is_admin"] and record["ingested_by"] != user["id"]:
        raise HTTPException(403, "Only the document's importer or the workspace owner can move it.")
    validate_project(payload.project_id)
    record["project_id"] = payload.project_id
    return document_summary(record)


@router.post("/embed", status_code=200)
def embed_library(payload: EmbedInput):
    """Embed passages without vectors (or everything, with force). Owner-stalled model load is one at a time."""
    global _embed_model
    if not embed_lock.acquire(blocking=False):
        raise HTTPException(429, "Embedding is already running. Wait for it to finish.")
    try:
        with storage.lock:
            todo = []
            existing = _load_vectors()
            for key in sorted(doc_chunks):
                if payload.force or key not in existing:
                    chunk = doc_chunks[key]
                    prefix = f"{chunk['heading']}. " if chunk["heading"] else ""
                    todo.append((key, (prefix + chunk["text"])[:MAX_CHUNK_TEXT]))
        if not todo:
            return {"embedded": 0, "model": MODEL_NAME, "message": "Every passage already has a vector."}
        model = get_embed_model()
        try:
            vectors = list(model.embed([text for _, text in todo]))
        except Exception:
            _embed_model = None
            raise HTTPException(503, "Embedding failed. No vectors were changed.")
        if len(vectors) != len(todo):
            _embed_model = None
            raise HTTPException(503, "Embedding returned an unexpected number of vectors. Nothing was saved.")
        with storage.transaction() as db:
            for (key, _), vector in zip(todo, vectors):
                db.execute(
                    "INSERT INTO doc_vectors(chunk_id,data) VALUES (?,?) ON CONFLICT(chunk_id) DO UPDATE SET data=excluded.data",
                    (key, json.dumps({"model": MODEL_NAME,
                                      "vector": [float(value) for value in vector]})))
        return {"embedded": len(todo), "total_chunks": len(doc_chunks), "model": MODEL_NAME,
                "message": f"Embedded {len(todo)} passage(s). Semantic search is now available."}
    finally:
        embed_lock.release()
