# Frontend Capability Guide — what Zero Magic's backend (and its AI) can do

Audience: whoever builds the Vue 3 + TypeScript frontend. Everything here is enforced
by the 288-test offline suite; the shapes are from the live OpenAPI (`/openapi.json`).

## 1. The world model

| Resource | Shape you can rely on | Notes |
|---|---|---|
| **Card** | `{id:int, title, goal, acceptance_criteria:[…], out_of_scope, stage, assignee:{kind:"human", identifier:"<personId>"} \| null, project_id:uuid\|null, depends_on:[int], source_prd_id, source_prd_revision, source_passages:[{id:"P1", quote}]}` | `GET /cards` adds computed `comment_count`. `source_*` only on AI-created cards |
| **Stage machine** | `Spec→Ready→Building→Checks⇄Building; Checks→Validation→Done; Validation→Building; Done terminal` | Building additionally requires every `depends_on` card to be `Done` (409 + ids listed) |
| **Person** | `{id, name, skills:[…], responsibility, has_login:bool}` | creation: owner only; edit: owner or self |
| **Project** | `{id:uuid, name (unique casefolded), color ∈ indigo/blue/teal/green/amber/orange/pink/purple, owner_id, card_count, brief_count}` | also returned inside `GET /boards` with per-status document counts |
| **Brief (PRD)** | `{id:uuid, title, content(80–18 000), source_name, project_id, revision, owner_id}` | every edit bumps `revision`; old revisions readable forever via `/prds/{id}/revisions/{n}` |
| **Document** | `{source_name, format, page_count, chunk_count, characters, project_id, status: pending\|processing\|ready\|failed, error, attempts, embedded_chunks}` | **retrieval only ever uses `ready`** docs |
| **Passage** | `{id:"<source>::00001", source, page\|null, heading\|null, text, text_normalized}` | page-less for Word; heading only when detected |
| **Proposal** | `{id:uuid, kind: cards\|assignments\|delete_project\|actions, status: pending\|confirmed\|cancelled\|superseded\|expired, data, expires_at}` | THE core UI object — see §3 |
| **Account/session** | cookie `zero_magic_session`, 30 days, HttpOnly SameSite=strict | setup-once owner; one-use 48h invitations; roles: owner (`is_admin`) vs member |

## 2. Endpoint map (52 operations, auth via cookie; every non-`/auth` route 401s anonymous)

```
Accounts    GET /auth/status · POST /auth/setup · POST /auth/login · POST /auth/logout
            GET /auth/me · POST /auth/invitations (admin) · POST /auth/invitation · POST /auth/accept-invite
Cards       POST/GET /cards · GET/PATCH/DELETE /cards/{id} · PATCH /cards/{id}/stage
            POST/GET /cards/{id}/comments · PATCH /cards/{id}/assignee
People      GET/POST /people · PUT /people/{id}
Projects    GET/POST /projects · PUT /projects/{id}
            POST /projects/{id}/deletion-preview · POST /projects/deletions/{token}/confirm|cancel
            POST /projects/{id}/ask                       (agent Q&A, board alias)
Briefs      GET/POST /prds · GET/PUT /prds/{id} · GET /prds/{id}/revisions/{r}
            POST /prds/{id}/breakdown
Documents   POST /documents/extract (plain text) · POST /documents/structure (labelled chunks)
Knowledge   GET/POST /knowledge · GET/PUT/DELETE /knowledge/{source} · POST /knowledge/search
            POST /knowledge/embed · POST /knowledge/ask
Boards      GET /boards · GET/POST /boards/{id}/documents · POST /boards/{id}/ask
Assistant   POST /assistant/chat · POST /assistant/agent
            POST /assistant/proposals/{id}/confirm · …/cancel
```

## 3. The AI's eight capabilities (and what the UI must render for each)

### 3.1 Conversational planning — `POST /assistant/chat {mode:"discuss"}`
Request: `{conversation_id:uuid, project_id?, prd_id?, prd_revision?, use_knowledge?, messages:[{role,content}]}` (≤40 msgs, ≤45k chars, last must be `user`).
Response: `{message, model, proposal:null, citations:[{id,source,page,heading,excerpt≤300}]}`.
Context the model actually sees: live board+people snapshot (project-filtered), optional attached brief, optional top-5 knowledge passages. `model` names the answering model (e.g. `openai/gpt-oss-120b`) — show it; `citations` render as chips.

### 3.2 Card planning with approval — `chat {mode:"plan"}`
Same request; response may carry `proposal {kind:"cards", data:{cards:[drafts], prd?, project_id, passages?}}` **or** a clarification question with `proposal:null`. Drafts: `{key, title, goal, acceptance_criteria, out_of_scope, depends_on:[keys], (breakdown only) source_passages:[P#]}`. UI: expandable preview list ("After: …", "From brief passages: P1 · P3"), then **Create N cards → confirm** → cards land `Spec`, unassigned. A second flow (`mode:"assign"`, `target_card_ids` ≤12) previews per-card person+reason and needs its **own separate confirm**.

### 3.3 PRD → cited breakdown — `POST /prds/{id}/breakdown {conversation_id, expected_revision, messages≤30}`
The brief is auto-split into numbered passages P1–P40; each returned draft card can cite `source_passages`. Errors: 409 brief/board changed, 413 too large, 429 (3/min + 1 in flight), 502 invalid output (incl. invented passage ids) — all with zero writes. Rate state survives restarts.

### 3.4 Knowledge search — `POST /knowledge/search {query, mode:keyword|semantic, limit≤10, project_id?}`
`keyword` = IDF-weighted, Persian/Arabic-normalized matching (returns `matches`); `semantic` = cosine over stored vectors (returns `similarity`) after `POST /knowledge/embed {force?}` (long first run — model download; single-flight → 429 busy). Retrieval only sees `ready` documents; a board's search = its docs + workspace-wide ones.

### 3.5 Grounded answering — `POST /knowledge/ask` / `POST /boards/{id}/ask` / `POST /projects/{id}/ask`
`{question≤2000, mode, limit 1–8}` → `{found, answer, model, passages_consulted, citations:[{id:"K1", document, page, heading, quote}]}`. The model answers **only** from retrieved passages, cites per claim, and when nothing matches the **application itself** returns `found:false` with a plain refusal (no model call). Providers down → 503. Render: answer + per-`[K#]` chip with quote.

### 3.6 Acting agent — `POST /assistant/agent {conversation_id, project_id?, messages}` (note: **no** `mode`/`use_knowledge` fields — extra fields 422)
The model gets six tools. Reads (`search_cards`, `read_card`, `ask_documents`) execute immediately server-side; writes (`create_card`, `move_card`, `add_comment`) **only ever stage**: response `{message, proposal:{kind:"actions", data:{operations:[{tool,args,preview}]}}, actions}`. Illegal intents (Spec→Done jump, move-to-Building with open prerequisites, blank titles, model-supplied `author`) come back to the model as tool errors with legal alternatives — they never reach a preview. Loop budget 4 rounds/16 tools/12 writes.

### 3.7 Prompt-injection resistance (a feature, design for it)
Text inside cards, briefs, documents, comments, tool results is framed to the model as untrusted data; the confirmation endpoint is not a tool. There is *no* API path by which AI output writes without a human confirm from the same account + conversation. Your UI can therefore treat every proposal as "an untrusted wish" — never auto-approve, ever.

### 3.8 Offline eval tooling (no UI)
`scripts/answer_questions.py`, `scripts/run_day19_evals.py` score retrieval/groundedness/refusal — quality numbers live in `eval/`, not the API.

## 4. The proposal lifecycle — build ONE component for it

States: `pending → confirmed | cancelled | superseded | expired(410)`. Rules:
- **One pending preview per conversation**: any newer user message supersedes the old one (your UI should clear it on 409).
- **Confirm is `{conversation_id, approve:true}`** (+ `confirm_name` for deletions). Replaying a successful confirm returns the **identical receipt** — safe "Retry" on network loss.
- Confirm applies through the same validated API paths; if board/team/brief drifted meanwhile → **409, nothing half-applied**; refetch + re-preview.
- `cancel` dismisses; after `confirmed` it's 409 ("cancel is not an undo").
- Receipt shape `{proposal_id, kind, status, message, cards:[affected]}` → upsert those cards into your board store.
Project deletion is its own dance: `deletion-preview` → token (10 min, account-bound) → type-exact-name screen → confirm; targets changing ⇒ 409.

## 5. Error contract (pin these in your client)

| Code | Meaning | Frontend behavior |
|---|---|---|
| 401 | not signed in / session dead | show auth screen (auto — every 401 outside `/auth` means expired) |
| 403 | cross-origin mutation or permission | surface; usually a dev-proxy misconfig |
| 404 | gone/foreign resource (incl. someone else's proposal) | drop local state, refetch |
| 409 | conflict: bad stage move, stale/expired-ish preview, drift, duplicate titles, occupied name, delete blocked | show server `detail` verbatim — messages are pinned and human-written |
| 410 | preview expired | re-request preview |
| 413 | too large (chat/brief/2 MB docs) | ask to shorten/split |
| 415 | wrong content-type/extension | you forgot JSON headers or unsupported file |
| 422 | validation; `detail` may be a Pydantic array | flatten to `"field: message; …"` (see `api()` in today's app.js) |
| 429 | rate: logins 20/15min, breakdown 3/min+1 flight, import 3/min, embed busy, previews full | "wait", disable button |
| 502 | model output invalid — **nothing was written** | retry/clarify |
| 503 | provider/config failure | retry later; answers never fabricated |

## 6. Hard limits worth mirroring in UI

Chat ≤40 msgs/45k chars (guard 38/43k) · breakdown msgs ≤30/18k · previews ≤12 ops · assign targets ≤12 · briefs 80–18k chars, ≤100 · docs ≤2 MB, PDF ≤50 pages, chunks: ≤800/doc, ≤2500 chars, library ≤60 docs/3000 passages · search limit ≤10 · ask ≤8 · comments ≤10k · passwords 12–128 chars · usernames `[a-z0-9_.-]{3,40}` · sessions 30 d · invites 48 h one-use · proposal TTL 30 min · deletion preview 10 min.

## 7. Interaction rules (the stuff that bites)

1. **Same-origin only.** Mutations need `application/json` + same-origin; the frontend is served BY FastAPI at `/` (`/static` mount). A Vite dev server on :5173 must proxy `/api` + `/` to :8000 or you'll see 403; simplest: build → serve via uvicorn, Ctrl+F5. Cookies are host-scoped — always use `127.0.0.1` (or `localhost`), consistently.
2. **`conversation_id` is per-tab** (`crypto.randomUUID()`); it scopes every preview. Losing it loses confirm rights.
3. **No websockets.** Threads poll every 8 s while open; board changes need Refresh. Do not invent realtime — the backend has none.
4. **Ingest is synchronous** — `POST /boards/{id}/documents` returns a terminal status (`ready`/`failed`); still render all four statuses (crash-swept records exist).
5. **Sanitize markdown** with the vendored marked+DOMPurify allowlist; model output is never raw HTML. `[K1]`/`P3` markers are plain text you then decorate.
6. **Long operations:** chat/breakdown up to ~2 min (timeouts: chat 135 s, embed minutes first run) — disable conflicting controls while busy (house pattern), and warn before closing dialogs.
7. **Exactly one Uvicorn worker**; in-memory snapshots. Never run two servers against the same DB; never run import/reset scripts with the server up.
8. **Never trust client identity:** authors/assignees/approvers come from the session; payloads with `author`/`author_id`/`stage`-in-PATCH/etc. are 422s, not features.

## 8. Recommended Vue shape (maps to the plan's Week 6)

Views: **Board** (6 stage columns, project×person filters, inline edits, legal-transition stage select, delete confirm) · **Card drawer** (fields, prerequisites list, brief/passage provenance chips, thread w/ polling) · **AI pane** (chat w/ toggles 📚/🤖, ONE reusable `ProposalPreview` for kinds cards/assignments/actions, citation chips, approve/change/dismiss) · **Briefs** (library, editor with revision-conflict UX, file-extraction review) · **Documents** (multi-upload → passage review → save w/ board attach, status chips, embed, search) · **Projects** (colors, counts, type-name deletion review) · **People** (profiles, invites) · **Auth** (setup | login | `#invite=` modes).
Stores: Pinia per resource + a `proposals` store owning the lifecycle (§4). Generate a typed client from `/openapi.json` so contract changes break the build — that is literally the Week-6 deliverable.
