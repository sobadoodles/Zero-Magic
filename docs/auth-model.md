# Auth model — roles, endpoint families, and the tests that lock them

> Deliverable 6 of the current plan. Maps every "done when" clause in the
> Week-6 AuthN/AuthZ plan to the specific test that enforces it, and states
> the one honest boundary (no real Bearer tokens for agents — parked in
> Week-6 plan, see §6).

## 1. Roles

There are three identities in the system, only two of which are accounts, and
each of those has two credential paths.

| Identity | Where it lives | How it authenticates | What it can do |
|---|---|---|---|
| **Owner** | `users.is_admin = 1` (`app/storage.py:60`) — exactly one row, seeded by `POST /auth/setup` (`app/auth.py:116–138`) | **Cookie** `zero_magic_session` or **Bearer** `Authorization: Bearer <api_token>`; both resolve to the same `users` row | All member powers **plus** invitations, people creation, any-record override, and minting / listing / revoking API tokens (mint + revoke additionally require the cookie path) |
| **Member** | `users.is_admin = 0` — any second account via `POST /auth/accept-invite` (`auth.py:199–215`) | Cookie (Bearer minting is admin-only, so members never have tokens) | Board use: cards, comments, briefs, projects, knowledge — with per-record ownership gates |
| **Agent (assistant)** | No account. Model calls run *under the signed-in user's session* inside `app/assistant.py` | Cannot present credentials of any kind | Only **stages** writes as proposals; the human's own confirm finalises them |

The design law (AGENTS.md / CLAUDE.md / ADR-001) is that the agent is a
*preview producer*, never a writer: `POST /assistant/proposals/{id}/confirm`
has no tool binding, requires `Depends(require_user)`, and re-checks the
account-bound `user_id` on the proposal — so a planted instruction in a card
title or a brief body cannot become a write.

## 2. Endpoint families × permission

Legend: **✓** allowed · **403** forbidden · **404** hidden · **—** no such route
· **own** allowed only for records the caller owns or created.

### Accounts (`/api/v1/auth/*`)

Legend: `Cookie` means the session-cookie path; `Bearer` means `Authorization: Bearer <token>`.

| Route | Owner | Member | Unauth | Notes |
|---|---|---|---|---|
| `GET /status` | ✓ | ✓ | ✓ | Public, reveals whether setup is needed |
| `POST /setup` | — | — | ✓ | One-shot: 409 forever after the first account |
| `POST /login` | ✓ | ✓ | ✓ | Rate-limited per IP and per username |
| `POST /logout` | ✓ | ✓ | 401 | Deletes the session row (cookie-only action) |
| `GET /me` | Cookie ✓ · Bearer ✓ | Cookie ✓ · Bearer ✓ | 401 | |
| `POST /invitations` | ✓ | **403** | 401 | `Depends(require_admin)` (`app/auth.py:171`) |
| `POST /invitation` (validate) | ✓ | ✓ | ✓ | Token-only; returns name |
| `POST /accept-invite` | ✓ | ✓ | ✓ | Once per token, 48 h TTL |
| `GET /tokens` | Cookie ✓ · Bearer ✓ | 403 | 401 | `Depends(require_admin)`; metadata list, never returns raw token |
| `POST /tokens` | **Cookie only** | 403 | 401 | `require_cookie_admin` — Bearer caller gets 403 "browser session" |
| `DELETE /tokens/{id}` | **Cookie only** | 403 | 401 | Same guard; own tokens (404 otherwise, 409 if already revoked) |

### Cards & comments (`/api/v1/cards/*`)

Router-level `Depends(require_user)` (`app/cards.py:15`). Every signed-in
member may create, list, read, patch, delete cards and add comments. There is
**no per-card privacy** (PROJECT-KNOWLEDGE.md §5 non-goal). Comment author is
server-controlled; sending `author`/`author_id` in the payload is a 422.

### People (`/api/v1/people`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `POST /people` | ✓ | **403** | `Depends(require_admin)` (`app/team.py:47`) |
| `PATCH /people/{id}` | ✓ | own (else 403) | `team.py:56–58`: `"Only the owner or this person can edit this profile."` |
| `PATCH /cards/{id}/assignee` | ✓ | ✓ | Human-kind only; unknown `person_id` → 404 |

### Briefs (`/api/v1/prds/*`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `GET /prds`, `GET /prds/{id}` | ✓ | ✓ | Shared library, no privacy |
| `POST /prds` | ✓ | ✓ | Sets `owner_id = user.id` (`prds.py:61`) |
| `PUT /prds/{id}` | ✓ | own (else 403) | `prds.py:88–89`: `"Only the brief's creator or owner can edit it."` |
| `POST /prds/{id}/breakdown` | ✓ | ✓ | Rate-limited: 3/min + 1 in-flight |

### Projects (`/api/v1/projects/*`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `GET /projects` | ✓ | ✓ | Includes live `card_count`/`brief_count` |
| `POST /projects` | ✓ | ✓ | Sets `owner_id = user.id` |
| `PUT /projects/{id}` | ✓ | creator (else 403) | `projects.py:39–40`: `"Only the project creator or workspace owner can edit or delete it."` |
| `POST /projects/{id}/deletion-preview` | ✓ | creator (else 403) | Same rule |
| `POST /projects/deletions/{token}/confirm` | ✓ | account-bound (else 404) | Token belongs to a specific `user_id`; a foreign account reaches 404, not 403 |

### Knowledge library (`/api/v1/knowledge/*`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `GET /knowledge`, `POST /knowledge/search`, `POST /knowledge/ask` | ✓ | ✓ | Shared, board-scoped retrieval |
| `POST /knowledge` (save) | ✓ | ✓ | Records `ingested_by = user.id` |
| `DELETE /knowledge/{source}` | ✓ | importer (else 403) | `knowledge.py:211–212`: `"Only the document's importer or the workspace owner can remove it."` |
| `PUT /knowledge/{source}` (re-attach) | ✓ | importer (else 403) | `knowledge.py:357–358`: same wording |

### Assistant & agent (`/api/v1/assistant/*`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `POST /assistant/chat` | ✓ | ✓ | Discussion never writes |
| `POST /assistant/agent` | ✓ | ✓ | Read tools run; write tools stage |
| `POST /assistant/proposals/{id}/confirm` | ✓ | own (else 404) | `assistant.py::confirm` checks account binding |
| `POST /assistant/proposals/{id}/cancel` | ✓ | own (else 404) | |

### Documents (`/api/v1/documents/*`)

| Route | Owner | Member | Notes |
|---|---|---|---|
| `POST /extract`, `POST /structure` | ✓ | ✓ | 3/min per account, 2 workers total, no writes |

## 3. The "done when" clauses mapped to their tests

The Week-6 AuthN/AuthZ deliverable's acceptance text is
`hash ✓ · 401 ✓ · 403 ✓ · tests prove each`, plus *"Real API tokens — Bearer
for agents — is the one genuine gap"*. Each clause is locked by a named test:

| Clause | Where it lives in code | Test that proves it |
|---|---|---|
| Passwords are **scrypt-hashed**, not plaintext | `hash_password` (`app/auth.py:52–55`) writes `scrypt$<salt-hex>$<key-hex>` | `tests/test_persistent_workspace.py::test_setup_once_and_password_hash` |
| Anonymous callers reach **401**, not 200/403 | `require_user` (`auth.py:78–87`); routers set `dependencies=[Depends(require_user)]` | `tests/test_persistent_workspace.py::test_private_reads`, `::test_private_write`; `tests/test_documents.py::test_auth_required`; `tests/test_boards.py::test_boards_require_signin` |
| Wrong-role callers reach **403** | `require_admin` (`auth.py:90–93`); per-record owner checks in `team.py`, `prds.py`, `projects.py`, `knowledge.py` | `tests/test_persistent_workspace.py::test_invite_once_and_owner_permissions`; `tests/test_prds.py` (member-on-others'-brief); `tests/test_projects.py` (member 403s); `tests/test_knowledge.py` (re-attach 403 non-importer) |
| Login attempts are **rate limited** and survive restarts | `login_attempts` table, 20 fails / 15 min per IP **and** per username (`auth.py:147–156`) | `tests/test_persistent_workspace.py::test_rate_limit` |
| Sessions are **revocable** (logout, expiry, regeneration) | `logout` deletes the row (`auth.py:163–167`); `invitation` regeneration deletes prior rows (`auth.py:177`); expired rows pruned at login (`auth.py:98`) | `tests/test_persistent_workspace.py::test_cookie_and_logout_revocation`, `::test_expired_session`, `::test_regenerating_invite_revokes_old`, `::test_expired_invite` |
| CSRF / cross-site mutations are **blocked** | `security_middleware` (`app/main.py:31,33`) | `tests/test_persistent_workspace.py::test_csrf_guards` (parameterised) |
| Comment author is **server-controlled** (spoofed `author_id` → 422) | `cards.add_comment` derives from session | `tests/test_persistent_workspace.py::test_server_controls_comment_identity`; `tests/test_assistant_actions.py::test_comment_rejects_unknown_author_id` |
| Proposals are **account-bound** (foreign `user_id` → 404) | `assistant.confirm` + `projects.confirm_deletion` | `tests/test_persistent_workspace.py::test_proposal_account_bound`; `tests/test_assistant_actions.py::test_other_conversation_cannot_confirm` |
| AI-written operations **cannot skip confirmation** | Model has no confirm tool; every write goes `preview → approve → receipt` | `tests/test_assistant_actions.py::test_injected_card_text_cannot_trigger_writes`; `tests/test_agent_actions.py::test_injected_card_text_cannot_self_apply` (unauth self-confirm → 401) |
| **Real Bearer API tokens** for external callers (last gap the plan named) | `require_user` Bearer fallback (`auth.py:78–110`); `api_tokens` table (`storage.py`); `require_cookie_admin` for mint/revoke (`auth.py`) | `tests/test_api_tokens.py` — 22 tests covering positive Bearer read/write/assistant, bad / expired / revoked tokens all 401, escalation guards, admin-only for members, cap at 20, plaintext never in DB, `last_used_at` updates only on success, password reset revokes tokens |

## 4. What "done" looks like

- ✅ **Hash** — `hash_password` writes scrypt with per-account salt; verify is
  constant-time; DB dump never contains a password.
- ✅ **401** — every business router declares `require_user`; anonymous hits
  return 401 with a generic message.
- ✅ **403** — `require_admin` for owner-only, per-record `owner_id`/`ingested_by`
  checks for ownership-gated writes; unknown-account foreign proposals return
  404 (not 403) so enumeration cannot probe proposal IDs.
- ✅ **Tests prove each** — the table in §3 maps every clause to a specific
  named test.

## 5. Honest boundaries (recorded, not silent)

1. **API tokens carry the human owner's authority.** `Authorization: Bearer
   <token>` resolves to the same `users` row and role as a session cookie,
   so anything the browser owner can do the token can do — *except* manage
   more tokens. The mint/list/revoke surface requires the browser cookie
   path (`require_cookie_admin`) so a leaked token cannot mint a
   replacement, which is what makes revocation actually revoke. Full
   contract: `docs/specs/api-tokens.md`.
2. **Tokens are unscoped.** A token is not a subset of permissions; it is the
   whole owner. Scoped tokens (`read-only`, `board-only`, etc.) would need a
   router-level allowlist — recorded as out-of-scope in the spec.
3. **No per-card privacy.** A signed-in member (or a bearer caller acting as
   that member) sees every card. Explicit non-goal
   (PROJECT-KNOWLEDGE.md §5).
4. **No audit log.** `login_attempts` (rate-limit evidence) and
   `api_tokens.last_used_at` are the only durable security-relevant
   records. See A09 in `architecture.md` OWASP checklist.
5. **Single-owner workspace.** `POST /auth/setup` locks permanently after one
   account, so ownership is *effectively* "whoever set up first plus whoever
   the owner invites". Multi-owner / owner-handoff is out of scope for
   prototype.
6. **Sessions and cookies treat `localhost` and `127.0.0.1` as different
   hosts** — cross-host replay will not authenticate, which is correct, but
   switching hosts logs the user out (AGENTS.md). Bearer calls have no
   host-binding concept, so they work from either; the TrustedHost gate
   still applies to the whole HTTP layer.

## 6. Cross-references

- `architecture.md` — **Security — OWASP Top 10 applied** (§A01, §A02, §A03,
  §A04, §A05, §A07, §A08) all point back to tests named here, and to the
  Bearer path via §A01 escalation guards + §A05 cross-origin allowance.
- `docs/specs/api-tokens.md` — the full Bearer contract: schema, lifecycle,
  limits, errors, and out-of-scope notes.
- `docs/specs/agent-tools.md` — the canonical model for AI-writable
  operations; the proposal lifecycle this table relies on. Bearer tokens
  do not weaken this — the model still has no credentials and no confirm
  tool.
- `docs/specs/review-checklist.md` — the process that requires a "Known
  limitation" line for every "not-yet-fixed" item above.
