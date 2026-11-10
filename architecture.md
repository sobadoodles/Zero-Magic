# Architecture — Weeks 1–2

> Historic baseline. Weeks 5+ live in the **"Architecture — Week 5 (system design)"**
> section at the end of this file; the honest assessment of the code is
> [`docs/architecture-critique.md`](docs/architecture-critique.md). "Out of scope"
> below listed database/persistence — since Week 3 that has *changed*: SQLite with
> transactional snapshots; PostgreSQL is decided below (ADR-002/003).

## Goal
Build a FastAPI backend for managing work cards, comments,
and assignment through a controlled development workflow.

## Scope
- Create, list, read, update, and delete cards.
- Validate request and response data.
- Enforce card-stage transitions.
- Add and list comments.
- Assign a card to one human or agent.
- Store data in memory.
- Test behavior with pytest.

## Out of scope
- Frontend
- Database and persistence
- Authentication and full user management
- Automated coding-agent runner
- Deployment

## Request lifecycle
Client → FastAPI route → input validation → application rules
→ in-memory storage → response

The client can initially be FastAPI's interactive /docs page.

## Card data
- id: server-generated integer
- title: required, non-empty text
- goal: required, non-empty text
- acceptance_criteria: list of non-empty strings; initially optional
- out_of_scope: optional text
- stage: defaults to Spec
- assignee: optional; one human or agent

Assignee:
- kind: human or agent
- identifier: non-empty text

Identifiers are labels for now, not authenticated identities.

## Comment data
- id: server-generated integer
- card_id: an existing card's ID
- author: non-empty identifier
- text: non-empty text

## Proposed stage transitions
- Spec → Ready
- Ready → Building
- Building → Checks
- Checks → Validation
- Checks → Building, when checks fail
- Validation → Done
- Validation → Building, when sent back

Done is terminal for this version.
All other transitions are rejected.

These rules model the workflow only. This version does not
verify CI results, pull requests, merges, or human approval.

## API endpoints
- POST   /api/v1/cards
- GET    /api/v1/cards
- GET    /api/v1/cards/{card_id}
- PATCH  /api/v1/cards/{card_id}
- PATCH  /api/v1/cards/{card_id}/stage
- DELETE /api/v1/cards/{card_id}
- POST   /api/v1/cards/{card_id}/comments
- GET    /api/v1/cards/{card_id}/comments

The general card-update endpoint cannot change the stage.
Stage changes must use the dedicated endpoint.

## Response rules
- 201: card or comment created
- 200: successful read or update
- 204: card deleted; no response body
- 404: card does not exist
- 409: stage transition is not allowed
- 422: request data is invalid

## Storage limitations
Data is lost when the application restarts.
Use one application process while storage is in memory.
Deleting a card also deletes its comments.

---

# Architecture — Week 5 (system design)

> **Status note:** this section records the AGREED TARGET (see ADRs at the bottom —
> "accepted" means decided, not yet built) plus the one tier that already exists.
> As of this writing: ✅ **domain** tier shipped (`app/domain/card_state.py`, pure,
> 8 tests) · ⬜ **services** tier planned (ADR-001/004) · ⬜ **repository ports +
> adapters** planned (ADR-002/003) — routes today still carry
> `@storage.synchronized` and mutate the snapshot store directly.
> The honest current-state analysis is `docs/architecture-critique.md`.

## Component diagram — the whole funnel (TARGET shape; "today" markers per node)

```
  browser ────────► FastAPI app ── one worker today; ADR-002 lifts it on Postgres
  (vanilla JS)          │
   routers (thin HTTP adapters)
     auth · team · cards · assistant · prds · documents · knowledge · boards
        │ call                                        ▲ map errors → HTTP
        ▼                                             │
   services (orchestration + rules)
     proposals engine · chat/agent loops · breakdown ·
     knowledge ingest · grounded QA · project deletion
        │ check
        ▼
   domain (pure, I/O-free)
     card_state stage machine · document_qa GroundedAnswer
        │ ports
        ▼
   repositories / unit of work
     ports · sqlite snapshot adapter (storage.py, today)
           · postgres adapter + alembic (target, ADR-002/003)
        │
   ┌────┴───────┬──────────────┬───────────────┐
   ▼            ▼              ▼               ▼
 SQLite /    Groq APIs      parser child     Week 7+:
 Postgres    (chat +        process          Gitea+Actions CI,
 (1 port)    instruct)      (PDF/DOCX,       runner worktrees,
                            bounded)          Vue 3 front
```

## The path of one card through the system

1. **Birth (human or agent).** `POST /cards` → `CardCreate` validation → counter id →
   stage `Spec` → one SQLite transaction. Via AI: chat/plan or the agent's
   `create_card` tool → **immutable preview** → human `confirm` → *the same*
   `create_card` handler. There is no privileged path.
2. **Specification.** Criteria, scope, project label, comments; a PRD breakdown adds
   `depends_on` (acyclic, in-draft only) plus `source_prd_id/_revision` and
   `source_passages` provenance.
3. **Ready.** One legal move; assignment changes through a *separate* suggestion
   preview and confirmation.
4. **Building.** Guarded by the domain stage machine — every prerequisite `Done`, or
   409 listing the blockers. Agents pass the gate twice (staging + apply).
   Week 7-8: the runner claims Ready cards into `../wt/card-<id>` worktrees.
5. **Checks.** Week 7+: Gitea Actions (lint, tests, bandit, pip-audit, gitleaks);
   red goes back to Building.
6. **Validation.** A *separate* reviewer — human now, reviewer-agent plus human
   sign-off later; rejection returns to Building; approval → **Done**, and merge
   to `main` happens only through a reviewed pull request.
7. **Afterlife.** Terminal stage; comments persist; deleting a referenced card
   strips it from dependents and purges related proposals; project deletion
   previews the exact set and re-checks the snapshot at confirm.

## Decisions (ADRs)

### ADR-001 — Three tiers, one dependency direction
**Status:** accepted · **Context:** routes orchestrate and mutate global dicts;
cross-module cycles are masked by function-local imports (critique §1–4).
**Decision:** routers depend on services; services on domain + repository ports;
adapters implement ports; imports flow one way and a service never imports a
router. The pure stage machine (`domain/card_state.py`) is the pattern-setter:
rules take data + injected policies, never singletons. **Consequences:** the
Week-8 worker reuses services without FastAPI; 10 modules churn once; the offline
288-test suite is the safety net.

### ADR-002 — Dual-backend persistence behind one port
**Status:** accepted · **Context:** durability exists (SQLite snapshots) but the
plan names PostgreSQL + migrations, and multi-process safety needs row
transactions, not whole-state flushes. **Decision:** keep the SQLite snapshot
adapter as the zero-setup default (single-worker semantics, offline dev,
current tests untouched); add a PostgreSQL adapter selected by `DATABASE_URL`,
with configuration centralised in `app/config.py`. Both satisfy the same
repository ports. **Consequences:** two code paths, one contract suite; the
"exactly one worker" rule lifts only in Postgres mode.

### ADR-003 — Alembic owns the Postgres schema; SQLite keeps its bootstrap
**Status:** accepted · **Context:** `CREATE TABLE IF NOT EXISTS` at import cannot
express FKs/CHECKs/sequences or evolve over versions. **Decision:** alembic
migrations model the relational core for Postgres (cards with stage CHECK + FK
project, comments FK→card CASCADE, sessions/accounts FK'd, `doc_vectors`
FK→chunks CASCADE; jsonb payload columns stay where the schema is deliberately
fluid); SQLite keeps self-bootstrap as the dev-mode convenience. **Consequences:**
schema parity is enforced by contract tests, not shared DDL; Python-side purges
(`purge_proposals`, flush pruning) become database CASCADEs in the new adapter.

### ADR-004 — Unit of work belongs to services
**Status:** accepted · **Context:** `@storage.synchronized` on route functions lets
the HTTP layer schedule transactions; nesting works only via a re-entrancy
special case in `storage.transaction()`. **Decision:** each service use case opens
one unit of work (a confirm batch, an ingest phase set, a deletion apply); new
routers hold no transaction decorator; the decorator recedes into the SQLite
adapter during migration and is deleted from new code. **Consequences:** atomic
batch behaviour stops depending on call structure; worker code (Week 8) gets the
same guarantee without FastAPI.

### ADR-005 — Dependency injection through FastAPI providers
**Status:** accepted · **Context:** module-level singletons force test
reach-throughs (fixtures clear tables and dicts) and hide real dependencies.
**Decision:** a small container exposes services/repositories via `Depends`,
mirroring the existing `require_user` pattern; `stage_of` policies show the
target shape; auth session lookups move behind a repository like everything else.
**Consequences:** services become unit-testable with in-memory fakes; the legacy
suite keeps its reset fixtures until routes are converted one at a time.

### ADR-006 — Typed domain errors; HTTP stays an adapter concern
**Status:** accepted (migration rule) · **Context:** rules currently return
`(409, message)` or raise `HTTPException` across layers, while dozens of tests —
and agent tool-error contracts — pin exact public wording. **Decision:** new
domain code returns typed error/result values; routers map them to statuses with
byte-identical messages; existing raise-sites convert opportunistically, never in
a behaviour-changing sweep. **Consequences:** the domain stays framework-free
without breaking contracts; the pinned message tests double as the compatibility
harness during migration.