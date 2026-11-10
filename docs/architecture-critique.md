# Architecture Critique — the backend as it stands (Week 5)

Honest review of `app/` measured against coupling, cohesion, layering, and
dependency direction. Every claim names the file it is about. This document is the
input to the ADRs in `architecture.md`; item 1 of the Week-5 plan.

## What is genuinely good (keep)
- **Typed boundaries.** Every request passes Pydantic models with `extra="forbid"` and
  visible-text rules (`schemas.py`); nothing untyped reaches business logic.
- **One preview engine.** `assistant.save_proposal`/`confirm` give every risky operation
  the same lifecycle: immutable server-side preview → account-bound explicit approval →
  baseline drift rejection → idempotent receipt. Four different kinds (cards, assignments,
  delete_project, agent actions) already reuse it.
- **Guards live server-side.** Stage transitions and the Building prerequisite rule are
  enforced in `cards.change_card_stage`, so UI, agent, and tests face identical law.
- **Atomic snapshots.** `storage.transaction()` commits or restores *both* SQLite and the
  in-memory state (`restore()` on exception) — batch failures leave no half-writes.
- **A 288-test offline suite** with disposable DBs, mocked models, and real subprocess
  parsing is the strongest safety net a refactor could ask for.

## Problems and where each thing should move

### 1. Routes are the business layer (layering)
Handlers mix HTTP with orchestration. `assistant.confirm()` inlines: batch
validation, card creation ordering, draft-key→ID resolution, dependency and
passage stamping, assignee rollback lists — while decorated for locking and
typed by a request model. There is no place to reuse "apply a plan" from a
non-HTTP caller (the Week-8 worker will want it).
→ **Move** orchestration into `app/services/` (card service, proposal service,
breakdown service, knowledge service, QA service). Routers keep: parse request,
call service, map errors to HTTP.

### 2. Module-singleton coupling (coupling)
Ten modules do `from app import storage` and mutate `storage.cards/prds/...`
dicts directly; `cards.change_card_stage` reads storage inside what is now a
domain rule. The state of the app is effectively global.
→ **Move** all state access behind repository ports (`app/repositories/`);
services receive the repo. Partial start: the stage machine (`domain/card_state.py`)
now takes an injected `stage_of` policy instead of touching storage.

### 3. Persistence leaking into presentation (dependency direction)
`@storage.synchronized` on route functions means the HTTP layer schedules
transactions; the dependency arrow points the wrong way (presentation → storage
policy). Nesting works only because `transaction()` special-cases re-entrancy.
→ **Move** the unit of work into services; routers should never know what a
transaction is. (ADR-004)

### 4. Function-local imports as circular-dependency band-aids
`projects.ask_project` imports knowledge inside the body; `knowledge.ingest_document`
imports documents/projects inside; `boards` defers `validate_project`;
`assistant` defers `knowledge`. Each one is a cycle being hidden, not solved.
→ Resolved by the target direction **domain ← services ← routers**; shared rules
(`validate_project`, chunking, grounding prompts) move to places that depend on
nothing above them.

### 5. Big modules with mixed responsibilities (cohesion)
`assistant.py` alone holds: system prompts, the chat loop, tool schemas, read
executors, write staging, proposal storage, confirm engine, receipts.
`storage.py` holds schema, snapshot mechanics, counters, and unit-of-work.
→ **Split** assistant.py into `proposal engine / chat service / agent service`;
keep `storage.py` as the *SQLite adapter* only.

### 6. JSON-blob tables underuse the database (data modeling)
`cards/comments/proposals/prds/doc_chunks` are `(id, data TEXT)`. Real relationships
live in Python scans: comment counting is O(cards×comments); project-name
casefold-uniqueness is memory-only; deletions must hand-purge dependents,
proposals, and vectors (`purge_proposals`, `flush()`'s pruning lines). SQLite has
foreign keys (`PRAGMA foreign_keys=ON`) — and we still don't declare them.
→ **Move** to modelled tables with FKs/CHECKs for the relational skeleton
(cards.stage CHECK + FK project/person, comments FK card CASCADE, proposal
receipts, doc_vectors FK chunk CASCADE), keeping jsonb payload columns where the
schema is intentionally fluid (acceptance_criteria, operations).

### 7. `flush()` rewrites whole state every transaction
Fine for one worker at prototype scale; a per-request all-tables diff is O(library)
and the reason we forbid multi-process.
→ Row-level writes in the PostgreSQL adapter remove the constraint itself.

### 8. HTTP semantics inside domain rules; scattered config; auth bypasses the pattern
- `transition_error` returning `(409, message)` embeds HTTP into the domain
  (acceptable for byte-exact messages today; ADR-006 sets the typed-errors target).
- `os.getenv` reads scattered across `storage`, `llm`, `auth` at import time; the
  DB path is frozen at import (which forces `conftest` to hack it first).
- `auth.require_user` hand-rolls SQL session lookups inside a FastAPI dependency,
  duplicating connection logic everywhere it is used.
→ One `config.py`, one session repository, domain error types with adapters.

## Summary: what should move where
| Now | Target |
|---|---|
| routers → `storage` dicts directly | routers → **services** → **repositories** (sqlite \| postgres) |
| `@storage.synchronized` on routes | unit of work in services (ADR-004) |
| `assistant.confirm` orchestration | `services/proposals.py` + `services/cards.py` |
| domain rules returning (409, str) | typed domain errors; presentation maps (ADR-006) |
| `(id, data TEXT)` for everything | modelled relational core + jsonb fluid parts (ADR-002) |
| `CREATE TABLE IF NOT EXISTS` at import | alembic migrations for Postgres (ADR-003) |
| function-local imports to dodge cycles | strict one-way layering (ADR-001) |
| scattered `os.getenv` | `app/config.py` (ADR-002) |
| exactly one Uvicorn worker | lifted by Postgres row transactions (after ADR-002) |
