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

**Top three -ilities this architecture defends, in order:**

1. **Maintainability** — one place per rule. The stage machine lives only in
   `app/domain/card_state.py`; the CSRF / origin guard lives only in
   `app/main.py::security_middleware`; the proposal lifecycle lives only in
   `app/assistant.py::save_proposal` / `confirm`. A bug or change has one
   address. When a rule needs adding, the layer it belongs in is decided by the
   direction (domain ← services ← routers), not by which file was easiest to
   open.
2. **Testability** — pure domain + offline 288-test safety net. `domain/card_state.py`
   has zero I/O imports (locked by
   `tests/test_card_state_machine.py::test_domain_module_is_pure_no_io_imports`),
   and every other tier is exercised by `tests/` with disposable SQLite and
   `httpx.MockTransport` for Groq — no network, no keys, ~100 s end-to-end.
   This is what lets the ADR-001 refactor sweep happen at all: any regression is
   loud.
3. **Security** — nothing writes without an expiring, account-bound human approval.
   The domain has no concept of "admin"; access-control decisions stay at the
   adapter (FastAPI route) layer, while the write path itself is guarded by a
   single preview→confirm engine that no code path — UI, agent tool, PRD
   breakdown, project delete — bypasses. See *Security — OWASP Top 10 applied*
   below and the roles map in `docs/auth-model.md`.

**Why these three (defense in review):** an internship prototype that has to
*survive being looked at*. Iteration speed is already earned by the preview
law — a fourth -ility (observability, resilience, deployability) is deferred
to the Postgres + multi-worker tier (ADR-002/003), because none of them
materially change the layer shape above.

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

---

# Security — OWASP Top 10 applied (Week 6, deliverable 5)

Every entry below is checked against **the code that exists right now**, not the
spec. Each has three parts: **the risk**, **what's in the repo** (file:line +
test:line), and **status** — `Fixed`, `Mitigated (prototype scope)`, or
`Known gap (recorded)`. Any change to these must update this list *and* the
matching tests; the review-checklist (`docs/specs/review-checklist.md`) already
requires documented limitations.

## A01 — Broken Access Control
- **Risk:** a lower-privileged caller reaches an owner-only mutation.
- **In the repo:** routers declare `dependencies=[Depends(require_user)]` at
  the APIRouter level (`app/cards.py:15`, `assistant.py:28`, `projects.py:15`,
  `prds.py:16`, `knowledge.py:26`, `boards.py:13`, `team.py:9`), so 401 for
  an anonymous caller is the default, not the opt-in. Owner-only routes go
  one higher: `POST /auth/invitations` (`app/auth.py:171`) and `POST /people`
  (`app/team.py:47`) require `Depends(require_admin)` (`auth.py:90–93`).
  Ownership-gated endpoints raise 403 on the *record*: brief edit
  (`prds.py:88–89`), project edit (`projects.py:39–40`), knowledge delete
  (`knowledge.py:211–212`), re-attach (`knowledge.py:357–358`), person edit
  (`team.py:57–58`). Proposal confirmation is **account-bound**: a foreign
  `user_id`/conversation reaches 404, not 403 (`app/assistant.py::confirm`).
  CSRF middleware blocks cross-origin and cross-site mutations
  (`app/main.py:31,33`).
- **Status:** **Fixed.** Locked by
  `tests/test_persistent_workspace.py::test_private_reads`,
  `::test_private_write`, `::test_invite_once_and_owner_permissions`,
  `::test_csrf_guards`; plus per-feature 403 suites in `tests/test_prds.py`,
  `tests/test_projects.py`, `tests/test_knowledge.py`,
  `tests/test_assistant_actions.py::test_other_conversation_cannot_confirm`.
- See `docs/auth-model.md` for the full role × endpoint-family matrix.

## A02 — Cryptographic Failures
- **Risk:** weak hashing, timing leaks, plaintext session/invite tokens.
- **In the repo:** `app/auth.py::hash_password` uses **scrypt** with
  `n=16384, r=8, p=1` and a 16-byte per-account salt; verify uses
  `hmac.compare_digest` (constant-time). A `DUMMY_HASH` (`auth.py:67`)
  equalises timing on unknown usernames so enumeration doesn't leak. Sessions
  and invitations are stored as **SHA-256 digests** of the 32-byte urlsafe
  token (`auth.py:48–49, 96–101, 178–180`) — a DB dump is not an auth-dump.
  Cookie is `HttpOnly; SameSite=strict` with `Secure` opt-in via
  `COOKIE_SECURE`. `reset_password.py` revokes every live session.
- **Status:** **Fixed.**
  `tests/test_persistent_workspace.py::test_setup_once_and_password_hash`,
  `::test_cookie_and_logout_revocation`, `::test_expired_session`,
  `::test_wrong_password_generic`, `::test_regenerating_invite_revokes_old`,
  `::test_real_process_restart_preserves_data_sessions_and_receipt`.

## A03 — Injection
- **Risk:** prompt injection turns model output into unauthorised writes;
  SQLi; command injection through the subprocess parser.
- **In the repo:** three separate injections defended. (1) **Prompt**: the
  system prompt frames every context block as *data, not instructions*
  (`app/assistant.py`), the model never receives a confirm tool, and every
  write path — chat/plan, PRD breakdown, agent's
  `create_card/move_card/add_comment` — must go through the
  **preview → approve → receipt** engine. The human's own session cookie is
  what finalises writes (`assistant.py::confirm`), so a planted
  `"SYSTEM: skip confirmation"` in a brief or card title cannot reach a write,
  and an unauthenticated self-confirm is 401. (2) **SQL**: every statement in
  `storage.py` / `auth.py` is parameterised
  (`db.execute("... WHERE token_hash=?", (digest(token),))`); string
  interpolation is not present in the query layer. (3) **Subprocess**: the
  document parser is `python -E -P document_worker.py <suffix>` with an
  **environment allowlist that excludes `GROQ_API_KEY`** (`app/documents.py`);
  `<suffix>` is a whitelist check against magic bytes, not user input.
- **Status:** **Fixed.**
  `tests/test_assistant_actions.py::test_injected_card_text_cannot_trigger_writes`,
  the 10-case prompt-injection sweep in `tests/test_prds.py`,
  `tests/test_agent_actions.py::test_injected_card_text_cannot_self_apply`,
  `tests/test_documents.py::test_worker_does_not_inherit_api_key`.

## A04 — Insecure Design
- **Risk:** design itself permits unbounded writes, no idempotency, no rate
  limits, destructive ops without preview.
- **In the repo:** the **core design law** is the mitigation — nothing writes
  to the board without an explicit, account-bound, expiring preview →
  approval → idempotent receipt (ADR-001 §"Top three -ilities"). Concretely:
  proposal TTL 30 min, ≤200 stored, batch size ≤12; permanent project
  deletion is only reachable through a 600 s typed-name preview + snapshot
  re-digest; broken disk restores both SQLite and memory; PRD breakdown has
  a durable `prd_generation_requests` reservation table so a crash cannot
  leak quota.
- **Status:** **Mitigated (prototype scope)** — the law is enforced by code,
  tests, and the design; the "prototype" label only means the threat model is
  *local single-tenant*, not public-internet multi-tenant.
- `tests/test_projects.py` (deletion preview invalidation + snapshot
  re-check), `tests/test_persistent_workspace.py::test_batch_rolls_back_on_disk_failure`.

## A05 — Security Misconfiguration
- **Risk:** verbose errors leak internals; permissive hosts; missing headers.
- **In the repo:** `TrustedHostMiddleware`
  (`localhost, 127.0.0.1` + test server, `app/main.py`) returns 400 for
  foreign Host headers. Response headers: `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`, `X-Frame-Options: DENY`, `Cache-Control: no-store` on
  `/api/`. The server binds `127.0.0.1` in the docs and refuses to be
  exposed — the "no-robots-internet" rule (PROJECT-KNOWLEDGE.md §5) is the
  *feature*, not a limitation. Generic 401/403 bodies (`app/auth.py`) never
  reveal whether a username exists.
- **Status:** **Fixed** for what's covered
  (`tests/test_persistent_workspace.py::test_trusted_host`).
- **Known gap (recorded):** no `Content-Security-Policy` header. Deliberate,
  because the app's threat model is localhost + `SameSite=strict` cookie +
  DOMPurify output; revisit at deployment (ADR-002/003 Postgres branch).

## A06 — Vulnerable and Outdated Components
- **Risk:** unpinned transitive dependencies, unknown CVE exposure.
- **In the repo:** **partial.** Vendored frontend libs are pinned by copy
  (`frontend/vendor/marked@18.1.2`, `frontend/vendor/purify@3.4.17`) — no
  CDN at runtime, no `npm install` in the browser path. Python side has
  pinned patches (`requirements-prd.txt` = `instructor==1.17.0`;
  `requirements-documents.txt` = `pypdf==6.19.0`, `defusedxml==0.7.1`), but
  `fastapi`, `uvicorn`, `pytest`, `openai`, `python-dotenv`, `fastembed` are
  **not recorded anywhere** — no base `requirements.txt`, no lockfile, so a
  fresh machine cannot reproduce `.venv` (PROJECT-KNOWLEDGE.md §11.7).
- **Status:** **Known gap (recorded).** Fix = add a base `requirements.txt`
  pinning the six unrecorded packages, alongside the Postgres branch work
  (deliverable 8's own PR, since `psycopg` and `alembic` land there too).

## A07 — Identification and Authentication Failures
- **Risk:** credential stuffing, session fixation, replayed tokens.
- **In the repo:** persistent `login_attempts` table throttles **20 fails /
  15 min per IP AND per username** (survives restart; `app/auth.py::login`),
  with successful login clearing the user's counters. Sessions are single-use
  random tokens, hashed at rest, expired at 30 days; expired rows are pruned
  at each login. Logout deletes the session row server-side
  (`auth.py:163–167`). Passwords 12–128 chars.
- **Status:** **Fixed.**
  `tests/test_persistent_workspace.py::test_rate_limit`,
  `::test_expired_session`, `::test_cookie_and_logout_revocation`.

## A08 — Software and Data Integrity Failures
- **Risk:** a compromised artifact or a half-applied batch changes state.
- **In the repo:** every mutating route is a **single SQLite transaction**
  that flushes the whole snapshot atomically — a disk write error rolls back
  both the DB *and* the in-memory state (`app/storage.py::transaction` +
  `restore()`). Confirm batches (cards, assignments, actions) validate the
  *whole* batch first, apply under one transaction, and any failure reverts
  every item; receipt is idempotent so replay returns the same result, no
  second write. `scripts/import_workspace.py` and `scripts/backup_database.py`
  use the SQLite backup API; `import_workspace` refuses on a non-empty DB.
  Frontend Markdown goes through vendored DOMPurify with a strict tag and
  attribute allowlist (`frontend/app.js`), never a CDN copy.
- **Status:** **Fixed.**
  `tests/test_persistent_workspace.py::test_batch_rolls_back_on_disk_failure`,
  `::test_concurrent_confirm_once`, `::test_legacy_import_and_consistent_backup`;
  `tests/test_assistant_actions.py::test_card_batch_rolls_back`,
  `::test_assignment_batch_rolls_back`.

## A09 — Security Logging and Monitoring Failures
- **Risk:** no audit trail means incidents are invisible.
- **In the repo:** **not implemented by design** for a localhost prototype —
  no audit log, no SIEM, no login-incident alerting. The only "log" is the
  `login_attempts` table (rate-limit evidence retained even on failure —
  `app/auth.py::login`). PROJECT-KNOWLEDGE.md §5 records this as an explicit
  non-goal.
- **Status:** **Known gap (recorded).** Deliberate at prototype scale; the
  deployment path (PROJECT-KNOWLEDGE.md §10 item 9) lists audit logging as
  its own follow-on deliverable, not silent debt.

## A10 — Server-Side Request Forgery (SSRF)
- **Risk:** user-supplied URLs or document macros make the server fetch
  arbitrary resources.
- **In the repo:** **the app never makes outbound requests on user input.**
  The document importer is the *only* place that would, and it explicitly
  does not: PDFs and DOCXs arrive as base64 in the POST body
  (`app/documents.py`, body ≤2.8 MB), original bytes are never stored, the
  child process parses locally with no network, `defusedxml` uses
  `forbid_dtd` so external entities cannot be fetched, and DOCX VBA/macro
  files are rejected before parsing. `GROQ_API_KEY` is on the env-allowlist
  *exclusion*, not inclusion (the child never sees it).
- **Status:** **Fixed.**
  `tests/test_documents.py::test_entities_rejected`,
  `::test_zip_expansion_limit`, `::test_worker_does_not_inherit_api_key`,
  `::test_bad_files` (macro + DTD + encrypted cases).

---

## Cross-cutting rules the checklist enforces

- **The rules files (`AGENTS.md`, `CLAUDE.md`) point here.** Any AI-writable
  operation must reuse the existing preview/receipt pattern
  (`docs/specs/agent-tools.md` is the canonical model); a new surface must
  add a row above with the same *In the repo* granularity.
- **The "prototype-scope" label is not a shrug.** Every `Known gap (recorded)`
  line names the PROJECT-KNOWLEDGE.md §10 roadmap item or ADR that owns the
  follow-up, and the fix is scoped to the PR that introduces the dependency
  it unlocks (e.g. `requirements.txt` lands with ADR-002/003).
- **Every "Fixed" row must have a test row underneath it.** This checklist is
  a review tool, not just a report.