# Feature: Project brief to approved cards

## Goal
Let a signed-in teammate save requirements, discuss them, and turn them into a
small typed card plan with explicit prerequisites. Never create board cards just
because a document or model response says to.

## Contract
- `POST /api/v1/prds`: title, content (80–18,000 trimmed characters), source_name.
- `GET /api/v1/prds`: shared-workspace brief summaries, newest first.
- `GET /api/v1/prds/{id}`: the saved brief and revision.
- `PUT /api/v1/prds/{id}`: full edited brief plus expected_revision. Creator/owner only.
- `GET /api/v1/prds/{id}/revisions/{revision}`: immutable saved source revision.
- `POST /api/v1/prds/{id}/breakdown`: conversation_id, expected_revision, messages.
- `POST /api/v1/assistant/proposals/{id}/confirm`: existing explicit confirmation.

## Drafts and dependencies
A CardDraft has key, title, goal, acceptance_criteria, out_of_scope, depends_on.
Keys are draft-local strings, not database IDs. A Breakdown contains either
1–12 cards or one focused clarification. Dependencies must reference keys in the
same batch, be unique, not self-reference, and form an acyclic graph. Titles/keys
must be unique; acceptance criteria must be nonblank. Semantic quality still
needs real-model evaluation and human review.

On approval, cards are created together in Spec and unassigned. Draft keys are
resolved to server-generated integer IDs, including forward references. Each
card records source_prd_id and source_prd_revision. The receipt and dependency
edges commit in the same SQLite transaction. Approval retries are idempotent
while the saved receipt remains available under existing proposal retention.
Assignment uses the existing second preview/confirmation, not the PRD response.

A dependent may move to Ready. Moving it to Building is rejected with HTTP 409
until every prerequisite is Done. Deleting a referenced prerequisite is rejected.
Dependencies are read-only in this first UI, not a general DAG editor. Source
edits do not silently rewrite existing cards or edges.

## Boundaries and errors
- All routes require the existing local session login.
- Briefs are shared with signed-in members of this workspace, not private per user.
- Revisions protect against stale editing and stale source approvals.
- Board/team changes during drafting or before approval invalidate the preview.
- Invalid input 422; missing brief 404; unauthorized edits 403; conflicts 409.
- Maximum 3 breakdown requests per rolling minute/account and 1 in flight/account.
- Large combined context 413; invalid structured output after retries 502;
  provider failure 503. No partial card creation on these failures.
- Instructor uses the shared llm module, JSON mode, schema/graph validators,
  bounded correction attempts and fallback to the second configured model.
- Provider calls have 20-second timeouts, at most 2 response-validation attempts
  per model, at most 2 models. A crashed in-flight reservation expires after 120s.
- PRD and board text are source data, not authoritative tool/system instructions.
- A model can still misunderstand a requirement. Preview and confirmation are
  required; passing mocked application tests does not certify model quality.

## Frontend
Plan with AI -> Add brief -> paste or locally load a UTF-8 .txt/.md -> save/use ->
discuss -> Preview cards -> inspect dependency labels -> confirm creation ->
separately confirm assignments. Saving/attaching a brief never calls the model
or creates cards. Switching briefs starts a fresh conversation with a warning.
Unsupported file types are rejected before sending data. No PDF/Word parser yet.

## Out of scope
PDF/Word extraction, OCR, embeddings, retrieval/citations, workload optimization,
manual dependency editing, dependencies on existing cards, automatic edits to
old plans, saved chat transcripts, production deployment, and real-model evals.
