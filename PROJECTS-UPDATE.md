# Color-coded projects and permanent deletion

This patch builds on the working PDF/Word + saved-brief version and includes the Add brief popup fix. No new Python packages or API keys are needed.

## Safe installation

With your existing .venv active in C:\Zero Magic Project:

```powershell
python scripts/backup_database.py
```

Keep that backup private. Stop Uvicorn with Ctrl+C.
Commit your working version first. If starting a new branch:

```powershell
git switch -c feat/projects-and-deletion
```

Extract this ZIP OUTSIDE the project, then merge matching folders into the project root. Replace matching files only. Do not replace whole folders.

Modified: app/storage.py, schemas.py, cards.py, prd_schemas.py, prds.py, assistant.py, main.py; frontend/app.js, index.html, styles.css.
New: app/projects.py, tests/test_projects.py, docs/specs/projects.md, this guide.

Keep .env, .venv, .git, data/, backups/, frontend/vendor/ and all existing dependency files. Do not run account setup, old export/import, or reset the database. The new projects table is added automatically. Existing cards/briefs stay saved and start Ungrouped; no project memberships are guessed.

Run the focused tests (the previous temporary-DB conftest must still be installed):

```powershell
python -m pytest tests/test_projects.py tests/test_documents.py tests/test_prds.py tests/test_persistent_workspace.py -q
```

Launch with the same existing environment:

```powershell
python -m uvicorn app.main:app --reload
```

Open your usual site, Ctrl+F5, and sign in normally. Use exactly one Uvicorn worker, as before.

## Projects and labels

1. Click Projects in the header. Give a project a distinct name and choose one of eight colors.
2. Create another project with a different name/color.
3. Select All projects or a specific project in the board filter. The person filter can be combined with it.
4. Open an existing card and choose its Project label. It saves immediately. Set Ungrouped to detach a label without deleting anything. Clicking a board label opens that card for relabeling.
5. Add card uses the currently filtered project, or choose a project in the new-card form.
6. For AI planning, choose Planning project. With a fresh chat it defaults to the board's selected project. When you attach a brief, that brief's project controls its new cards instead.
7. In Add/Change brief choose Project before saving. NEW cards generated from it inherit the chosen project. Changing an old brief's project does NOT retroactively move existing cards; relabel those cards explicitly.
8. Creation previews show the project label too. The AI cannot override the selected project ID. Card/assignment approvals remain separate.

Project names are unique case-insensitively. Color choices can be reused, but names always appear too, so meaning never depends on color alone. Everyone sees the shared workspace's projects; these are organizational groups, not private access-control boundaries. Discussion/new-card model context is filtered to the selected project (Ungrouped means ungrouped cards); assignment context uses explicit target IDs. Brief context remains limited by the same existing size caps.

## Delete a single card

Open the card -> Delete card -> read and accept the confirmation.

This removes the card row and its comments from active SQLite storage. Related cached operation previews/receipts are purged to prevent stale references. The parent brief/project and team accounts remain. Existing prerequisites are protected: deletion is blocked if another card depends on this card. Remove dependent work first or keep the prerequisite. Deletion is permanent in the app; there is no trash/undo.

All signed-in workspace members retain the existing shared-card edit/delete permissions. Project management is more restricted: only a project's creator or workspace owner can rename/recolor/delete that project.

## Delete a whole project

Option A: Projects -> the project's Delete button.

Option B: In Plan with AI, type the explicit command:

```text
delete project Atlas website
```

Replace Atlas website with the EXACT existing project name (matching ignores letter case for lookup). Or select a Planning project and type:

```text
delete this project
```

The chat command is deliberately handled by the application, not by a model guessing which project to destroy. It opens the same deletion review screen. Other natural-language requests may be discussed normally; this is not unrestricted model tool calling.

The review lists the precise project name, card titles/IDs, brief titles, comment count, and irreversible-deletion warning. Type the exact displayed project name, then press Permanently delete project. Typing 'yes' in chat alone DOES NOT delete a project. Keep project, X, or Escape closes the screen without applying deletion and requests revocation of its preview token. Unused previews also expire automatically.

After confirmation the active DB removes:
- That project's label/record.
- All cards explicitly assigned to it, including Done cards.
- Those cards' comments.
- Briefs explicitly assigned to it and their stored revisions.
- Related cached planning/assignment previews and receipts.

Other projects, Ungrouped tasks, people, accounts and sessions stay. A brief not explicitly assigned to the project is not deleted merely because it once generated a project card.

## Safety and expected conflicts

- Deletion previews expire after 10 minutes and are tied to the signed-in account. No model call can confirm one.
- Preview and approval are separate. The server rechecks the complete target project/cards/briefs/comments snapshot and permissions at approval. Any target change requires a fresh review.
- Other-project changes alone do not invalidate the preview. But cards in another project or Ungrouped that depend on the target's cards, or refer to its briefs as their source, BLOCK deletion. Resolve those links first; the app will not silently remove outside work. Moving a dependent card into the target project makes it part of the reviewed deletion scope—do so only intentionally.
- The complete delete is one SQLite transaction, including history removal and a minimal repeat-safe receipt. A failed DB commit restores the in-memory state too. Repeated approval returns the receipt instead of deleting more work.
- The UI refreshes after deletion and clears stale chat/preview context. Browser tabs opened elsewhere may still display cached old content until refreshed; the server no longer serves the deleted records.
- SQL DELETE is not forensic secure erasure. Backups, WAL/filesystem remnants, already-sent Groq requests and other clients' cached content are not retroactively erased. A minimal operation receipt keeps the project name/IDs/counts, not deleted card or document text. Do not interpret this as a privacy/compliance erasure system.

## Validation

The test suite covers label persistence, project inheritance, duplicate names/colors, auth/creator permissions, card/comment SQL deletion, project cascade including brief revisions, other-project preservation, external dependency/source guards, stale/expired/account-bound previews, idempotence, rollback, and restart persistence. Browser QA covers real API operations and chat-triggered deletion review; existing planning-model replies are simulated during QA, not live Groq quality testing.

This feature does not add multi-project privacy, archive/trash/undo, arbitrary natural-language destructive tool calling, or automatic cleanup of external services. Back up first and test deletion with a disposable sample project.
