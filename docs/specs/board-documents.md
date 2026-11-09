# Board documents — attach, ask, and cite your sources

## Goal
Give every board (project) the documents its cards came from. Users attach PRDs and
reference documents to a project; anyone signed in can ask that board a question and get
an answer that only uses the retrieved passages, with a document + page + quoted passage
citation for every claim; and each draft card from a PRD breakdown records the exact
passages it was based on.

## Terminology: board = project
This app has one shared board and uses Projects as its organizing unit (labels, filters,
scoped planning). A "board" here is a Project. Documents with `project_id = null` are
workspace-wide and remain visible to every board's retrieval as well as to unscoped ask.

## Attaching documents to a board
- `POST /api/v1/documents/structure` (unchanged) extracts, labels, and returns reviewable
  passages — never writes, never calls the model.
- `POST /api/v1/knowledge` now accepts `project_id` on each document. `validate_project`
  rejects an unknown board (404); saved records carry `status:"ready"`. A document with a
  null project is workspace-wide.
- `PUT /api/v1/knowledge/{source_name}` `{project_id}` re-attaches a saved document to a
  different board (or detaches it). Only the importer or the workspace owner may move it
  (403 otherwise). It records no other change.
- The whole library still shares the Week-5 caps (≤60 docs, ≤3000 passages, ≤2500
  chars/passage).

## Asking a board — the grounded answer endpoint
- `POST /api/v1/projects/{project_id}/ask` = `{question (1–2000 visible chars),
  mode: keyword|semantic (default keyword), limit 1–8 (default 5)}`. Retrieval is scoped
  to that board's documents plus workspace-wide ones, using the same
  `knowledge.retrieve()` the library search uses.
- `POST /api/v1/knowledge/ask` is the same answerer with an optional `project_id` in the
  body; omit it to ask the whole workspace.
- Both share `app/document_qa.py` with the CLI, so the strict contract is identical:
  answer ONLY from the numbered passages; every claim cites its `[K#]`; if the passages
  don't hold the answer, `found=false` with a plain "The documents do not contain the
  answer…" line and NO citations. When a question matches no stored passage, the
  application answers "not found" itself without calling any model.
- Response: `{question, project/project_id, mode, passages_consulted, found, answer,
  model, citations:[{id, document, page, heading, quote}]}`. Unknown board → 404. A model
  that returns a citation id that was never given is dropped server-side; the CLI's
  evaluator flags it as a failure.
- Provider/configuration failure while answering → 503, never a guessed answer.
- All routes require the existing login + same-origin JSON guards. Passage text is
  untrusted data, never instructions; approvals and card writes stay out of this path.

## Retrieval used in the PRD breakdown — cards cite their sources
- `POST /api/v1/prds/{id}/breakdown` now splits the brief into numbered passages
  (`P1…P40`, using the same `chunk_page` label/section splitter as the library) and passes
  BOTH the passages and the live board context to the model.
- Each `CardDraft` gains `source_passages: [P#]` (unique, ≤6). The prompt tells the model
  to set it to the passages its card is based on, empty when none genuinely apply, and to
  NEVER invent passage ids.
- On breakdown, invented passage ids are rejected with **502 "The model invented brief
  passage ids. No preview was prepared."** — no preview, no writes.
- On confirm, each created card stores `source_passages:[{id, quote(≤200 chars)}]` beside
  its existing `source_prd_id` / `source_prd_revision`. The whole-brief link stays; the
  passage link is added. The field is optional, so old briefs without citations still
  confirm (their cards just get an empty list).
- The brief `content` field is no longer dumped whole into the model message; the numbered
  passage list is the source of truth instead.

## Frontend
- The Documents dialog gained a **Attach to project** select. Extract → review → save
  attaches the passages to the chosen board (or leaves them workspace-wide). Saved rows
  show the board's color label.
- Card details now show a **From the brief · source passages** block listing each cited
  passage id and its quote.
- The AI proposal panel shows "From brief passages: P1 · P3" on each draft card.
- Chat answers, when the 📚 Library is on, are scoped to the selected Planning project's
  documents plus workspace-wide ones; the existing `[K1]` citation chips still render.

## Failure/limit behavior
- Empty question / wrong shape / extra fields → 422 (Pydantic `extra:"forbid"`).
- Ask on a board whose documents don't cover the topic → a clean not-found answer, no
  model call, no fabricated citation.
- Semantic ask with no vectors yet → 503 (use keyword mode or run Embedding first).
- `validate_project` on attach/ask/brief-save rejects a stale board id after a permanent
  project deletion (404), and purging related cached operations still runs.

## Out of scope (this slice)
Automatic project inference from a document's text, cross-board answer synthesis, saved
ask history, reranking/hybrid search, OCR, per-document privacy, and AI edits to existing
cards. Citation support is a deterministic keyword check and the model's own [K#] ids, not
a semantic-entailment verifier. Board documents are still shared workspace data, not an
access-control boundary, and deletion is active-record removal, not forensic erasure.
