# Install the first PRD feature

This update is based on the login + SQLite version previously delivered. It does
not reset your database, recreate your account, or change the Groq key. If you
have customized these same files, back up/commit and review the diff before
replacing them.

## Before copying files

In your project terminal, one command at a time:

```powershell
Set-Location "C:\Zero Magic Project"
python scripts/backup_database.py
```

Keep the backup private. Stop the Uvicorn server with Ctrl+C in its own terminal.
You no longer need the old in-memory export/import procedure: this update extends
the existing SQLite database by adding tables. **Do not delete data/, .env,
.venv, or .git. Do not run the old import or owner setup again.**

Start a feature branch from your current pushed work:

```powershell
git switch -c feat/prd-breakdown
```

If that branch already exists, switch to it rather than repeating creation.

## Copy and install

Extract the ZIP somewhere outside the project. Merge its folders into the
project root, replacing only matching files. Don't replace the entire project.

Updated existing files:
- app/main.py — registers the PRD router.
- app/storage.py — adds PRDs, immutable source revisions, generation limits.
- app/assistant.py — selected brief context and confirmed dependency mapping.
- app/llm.py — Instructor structured output and bounded correction/fallback.
- app/cards.py — dependency defaults, Building guard, protected prerequisites.
- frontend/index.html, frontend/app.js, frontend/styles.css.

New files:
- app/prds.py, app/prd_schemas.py.
- requirements-prd.txt.
- tests/test_prds.py.
- docs/specs/prd-breakdown.md.
- examples/notification-preferences.md and this guide.

The ZIP also includes the isolated tests/conftest.py and the previous
27-case tests/test_persistent_workspace.py so the test command below has a known
baseline. Replace the old in-memory conftest if yours was not updated earlier.
It selects a temporary test database before any application imports.

With your EXISTING .venv active:

```powershell
python -m pip install -r requirements-prd.txt
```

Instructor wraps the existing OpenAI-compatible SDK. It validates model output
against Pydantic models, asks for a correction when necessary, then can use the
second configured Groq model. This installation needs internet access, but no
new provider account or API key. Do not install a package named sqlite3.

## Run the checks

```powershell
python -m pytest tests/test_persistent_workspace.py tests/test_prds.py -q
```

These tests use a temporary DB and fake model responses/transports, not your
real Groq key or live workspace. The older unauthenticated test suites still need
the auth-related updates described in START-HERE.md; do not interpret their 401
failures as a reason to remove login protections.

Then launch:

```powershell
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/ and press Ctrl+F5. Sign in with your existing account.
Use the same host you used previously; localhost/127.0.0.1 have separate cookies.

## Try one complete example

1. Open **Plan with AI -> Add brief**.
2. Click **Load .txt / .md** and select examples/notification-preferences.md.
   You can also type/paste your own requirements (80–18,000 characters).
3. Click **Save and use brief**. This saves requirements, not cards. It makes
   no model call. Source text is shared with signed-in workspace teammates.
4. Ask: "Keep this small. What should we build first?" The selected brief is
   included in the discussion request sent to your configured Groq model.
5. Click **Preview cards**. No cards should appear on the board yet.
6. Expand the proposed cards. Check goals, acceptance criteria, exclusions, and
   the **After: ...** dependency labels. A vague brief may produce a clarifying
   question instead; answer it and request a preview again.
7. Click **Create N cards** only when the plan is right. New cards are Spec and
   unassigned. The next preview suggests assignments, requiring its own approval.
8. Open a dependent card. It lists its prerequisite cards. You may put it in
   Ready, but Building is blocked until all prerequisites reach Done.
9. Refresh the browser or restart Python. Briefs and approved cards remain.
   To reattach a saved brief after reload: Add brief -> Saved briefs -> select it
   -> Save and use brief. An unchanged brief isn't unnecessarily versioned.

Each brief edit creates a revision and preserves earlier versions in SQLite.
Pending previews tied to an edited revision cannot be applied. Editing a brief
DOES NOT automatically change already-created cards; existing-card replanning is
still future work. New drafts reject exact existing card titles to reduce
accidental duplicates; this is not semantic duplicate detection.

To revise a pending plan, choose **Change this**, describe the change, and request
another preview. Don't press Create repeatedly to request a different plan.

## Limits and expected errors

- File loading: UTF-8 .txt/.md only, max 64 KB and 18,000 characters. File content
  is read locally, then saved as text after your Save action. Original binaries
  aren't uploaded or executed. PDF/Word extraction belongs to the next slice.
- Breakdown: max 12 draft cards, dependencies only within this draft, no cycles,
  max 3 requests/minute/account, only one breakdown at a time for that account.
- A 429 means wait for the running request/minute window; don't change accounts
  to bypass limits. Provider rate limits may last longer.
- A 409 mentioning an edited brief means reopen/reselect it. A board/team conflict
  means review a fresh preview. Nothing from that stale preview is created.
- A 409 duplicate title means ask for genuinely new work or edit the existing
  cards manually. AI changes to existing cards aren't implemented here.
- A 502 means structured responses failed validation after bounded retries. A
  503 means provider/configuration failure. Both leave board cards unchanged.
- PRD context and chat history have size caps; use a smaller first release or
  fresh conversation if told it is too large. Files are not a RAG index.

## Where to look in the code

1. prd_schemas.py — the contract: a card key, acceptance criteria, dependency DAG.
2. prds.py — save/read/update briefs; model call returns a preview only.
3. llm.py: ask_structured — validate/reask/fallback. Ask for at most two models
   from MODELS. Never put the Groq key in code.
4. assistant.py: confirm — resolve draft keys to real IDs in one transaction;
   confirmation retries return the existing saved receipt.
5. cards.py: change_card_stage — the same dependency guard applies to API calls,
   so a frontend or AI cannot skip a prerequisite by changing the UI.

For example, draft `form.depends_on = ["api"]` becomes stored
`form.depends_on = [42]` if the API card receives ID 42. No made-up integer IDs
from the model are trusted.

## Still outside this update

Document extraction/OCR/embeddings/retrieval, the full eval report, general board
tool calling, moving/commenting via AI, saved chat history, automatic edits to
existing plans, PostgreSQL/Vue migration, and production deployment remain open.
Continue to use exactly one Uvicorn worker with the current SQLite snapshot
implementation. Backups now include PRDs too; keep them outside GitHub.
