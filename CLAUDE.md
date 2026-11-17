# Zero Magic

Local single-workspace team board: FastAPI backend (`app/`) + dependency-free vanilla-JS
SPA (`frontend/`), SQLite persistence, Groq AI assistant. An internship prototype —
localhost-bound, **exactly one Uvicorn worker** (in-process locks and snapshots break with
multiple workers).

This file is the Claude Code companion to `AGENTS.md`. They intentionally overlap so that
whichever agent harness opens the repo first, it lands on the same three anchors: the
architecture ADRs, the OWASP checklist, and the auth model.

## Read first

- `PROJECT-KNOWLEDGE.md` — exhaustive, current (2026-11-09) reference: full API surface
  (52 ops), module map, storage design, limits, quirks, and the project's design laws.
  Consult it before adding or changing features.
- `architecture.md` — the six ADRs + the **Security — OWASP Top 10 applied** checklist.
  Any new feature must fit the three-tier dependency direction of ADR-001; any new
  AI-writable operation must match the pattern in `docs/specs/agent-tools.md`; any
  security-relevant change must add a row to the OWASP checklist in the same PR.
- `docs/auth-model.md` — the roles × endpoint-family matrix, plus each AuthN/AuthZ
  "done when" clause mapped to the specific test that proves it.
- Root `*.md` guides are per-week install notes; some are **stale**. `SETUP.md` still says
  "in-memory storage" (superseded by SQLite, see `START-HERE.md`). `PROJECTS-UPDATE.md`
  says a referenced card cannot be deleted — current `delete_card` instead strips
  dependency links (locked by `tests/test_projects.py`). Trust code + PROJECT-KNOWLEDGE.md.

## Commands

```powershell
# Use `.venv` — `.venv-1`/`.venv-2` are stray duplicates (.venv is canonical, has fastembed)
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload      # dev server -> http://127.0.0.1:8000
python -m pytest -q                          # full suite: ~280 tests, ~100 s, zero network
python -m pytest tests/test_cards.py -q      # single file (same for -k selectors)
```

- Tests use a throwaway DB: `tests/conftest.py` sets `ZERO_MAGIC_DB` **before any app
  import**. If pytest raises "Application imported before test database selection",
  something imported `app.storage` too early — restart the pytest session, don't fix by
  reordering inside the app.
- There is no base requirements.txt pinning fastapi/uvicorn/etc. Install patches:
  `requirements-prd.txt` (instructor), `requirements-documents.txt` (pypdf, defusedxml).
  Working env lives only in `.venv`; don't assume a fresh `pip install -r` reproduces it.
  This is OWASP A06 (Vulnerable Components) — recorded in `architecture.md`; fix = add
  `requirements.txt` alongside the Postgres branch work.
- No lint/format/typecheck tooling is configured. No CI, no git hooks.

## Environment

- `.env` (never commit): `GROQ_API_KEY` and `MODELS` (comma-separated, tried in order with
  fallback). `load_dotenv` runs in `app/llm.py` and `app/storage.py` — env is loaded by the
  app, not the shell. `ZERO_MAGIC_DB` overrides DB path; `ALLOWED_HOSTS`, `COOKIE_SECURE`
  are optional switches.
- DB: `data/zero_magic.sqlite3` (WAL). Payloads (cards, people, comments, proposals) are
  JSON records inside SQLite tables. Never edit the live file while the server runs.
- **Never run import/recovery scripts (`import_workspace.py`, `reset_password.py`) while
  the server is running.** `backup_database.py` is safe (SQLite backup API).
- Scripts that hit Groq (`try_model.py`, `answer_questions.py`, `run_day19_evals.py`)
  consume real quota unless run with free/offline flags (e.g. `--no-answering`).
- Test suite mocks model calls; no Groq key needed for `pytest`.

## Architecture & conventions

- Entry point `app/main.py`: mounts routers (`auth`, `team`, `cards`, `assistant`, `prds`,
  `documents`, `knowledge`, `boards`, `projects`), serves `frontend/` at `/static` and
  `index.html` at `/`. Card stage machine is the pure module `app/domain/card_state.py`.
- Frontend is one `app.js` (~1000 lines) + `index.html` + `styles.css`; Marked/DOMPurify
  are vendored in `frontend/vendor` (no npm, no CDN, no build step).
- API contract changes must update backend and frontend **together** — a cached old
  frontend against new backend returns 422s (docs blame Ctrl+F5 for this).
- Security middleware rejects cross-origin/cross-site `/api/` mutations and requires
  `application/json` (DELETE is exempt from the content-type check only). Tests must
  respect, not bypass, these guards.
- **Core design law: nothing writes to the board without an explicit, account-bound,
  expiring AI preview → approval → idempotent receipt.** Any new AI-writable operation
  must follow the existing proposal/receipt pattern (`docs/specs/agent-tools.md` is the
  model). Discussion responses and model output can never write directly.
- Sessions/cookies: `localhost` and `127.0.0.1` are different cookie hosts — be consistent.
- Access control: two account roles (owner `is_admin=1`, member) and one agent role
  (model, no account). The full matrix and each "done when" clause → test mapping
  lives in `docs/auth-model.md`. Do not add a third role or bypass `require_user` /
  `require_admin` without updating that file in the same PR.

## Git

- Active branch: `feat/document-retrieval` (feature branches off `master`:
  `feat/create-card`, `feat/prd-breakdown`, `feat/document-import`).
- Commit style: Conventional-Commits prefixes (`feat:` `fix:` `refactor:` `test:` `docs:`)
  with long descriptive messages explaining behavior changes and test counts.
