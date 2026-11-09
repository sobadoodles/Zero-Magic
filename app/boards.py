"""Board API. In this single-board app a "board" is a Project: the board id is the
project id. Boards own attached documents (with a live ingest status) and answer
grounded questions from their ready passages."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import knowledge, storage
from app.auth import require_user
from app.schemas import NonBlankText

router = APIRouter(prefix="/api/v1/boards", tags=["Boards"], dependencies=[Depends(require_user)])


class BoardAskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: NonBlankText = Field(max_length=2000)
    mode: str = Field(default="keyword", pattern="^(keyword|semantic)$")
    limit: int = Field(default=5, ge=1, le=8, strict=True)


def board(ident):
    from app.projects import validate_project
    validate_project(str(ident))
    return storage.projects[str(ident)]


@router.get("")
@storage.synchronized
def list_boards():
    boards = []
    for project in sorted(storage.projects.values(), key=lambda p: p["name"].casefold()):
        docs = [record for record in storage.doc_files.values() if record.get("project_id") == project["id"]]
        counts = {"pending": 0, "processing": 0, "ready": 0, "failed": 0}
        for record in docs:
            counts[record.get("status", "ready")] += 1
        boards.append({"id": project["id"], "name": project["name"], "color": project["color"],
                       "card_count": sum(c.get("project_id") == project["id"] for c in storage.cards.values()),
                       "brief_count": sum(d.get("project_id") == project["id"] for d in storage.prds.values()),
                       "document_count": len(docs), "documents_by_status": counts})
    return {"boards": boards}


@router.get("/{board_id}/documents")
@storage.synchronized
def board_documents(board_id: UUID):
    ident = board(board_id)["id"]
    records = [knowledge.document_summary(record) for record in storage.doc_files.values()
               if record.get("project_id") == ident]
    records.sort(key=lambda record: record.get("ingested_at", ""), reverse=True)
    return {"board": {"id": ident, "name": storage.projects[ident]["name"]}, "documents": records}


@router.post("/{board_id}/documents", status_code=201)
def upload_board_document(board_id: UUID, payload: knowledge.IngestInput, user=Depends(require_user)):
    """Ingest one file for this board: pending -> processing -> ready | failed.

    The upload is parsed with the same bounded, isolated worker as /documents/extract;
    original bytes are never stored. Failures persist on the document record with a
    reason and can be retried by re-uploading the same file name.
    """
    ident = board(board_id)["id"]
    record = knowledge.ingest_document(payload, ident, user)
    return {"board": {"id": ident, "name": storage.projects[ident]["name"]}, "document": record}


@router.post("/{board_id}/ask")
def ask_board(board_id: UUID, payload: BoardAskInput):
    """Answer ONLY from this board's ready documents (plus workspace-wide ones), citing
    document, page, and the quoted passage for every claim; plainly not-found otherwise.
    """
    ident = board(board_id)["id"]
    return {"question": payload.question,
            "board": {"id": ident, "name": storage.projects[ident]["name"]},
            "mode": payload.mode,
            **knowledge.perform_ask(payload.question, ident, payload.mode, payload.limit)}
