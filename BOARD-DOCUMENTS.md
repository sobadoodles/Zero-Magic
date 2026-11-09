# Board documents — attach, ask, cite

Short tour of the Week-6 slice (full contract: `docs/specs/board-documents.md`).
"Board" = **Project** in this app.

## Attach documents to a board

Browser: **Documents → Extract file(s) for review → Attach to project → Add to library**.
Saved rows show the board's color label; re-attach later with the API (`PUT
/api/v1/knowledge/{source}` `{project_id}`, importer/owner only). No select = workspace-wide
(visible to every board's answers too).

Via script (server stopped): import first, then sign in and attach in the UI — or POST
`{"documents":[{"source_name":…,"project_id":"<uuid>",…}]}` directly.

## Ask a board through the API

```powershell
$body = @{ question = "When is the reminder sent?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/projects/<project-uuid>/ask" `
  -Method Post -ContentType "application/json" -Body $body -WebSession $session
```

Response: `{ question, project, passages_consulted, found, answer, model,
citations: [{ id, document, page, heading, quote }] }` — every claim cites a passage, or
the answer states plainly "The documents do not contain the answer…" (with zero citations
and, when nothing matched at all, no model call happened).
Add `{"mode":"semantic"}` after pressing Embed. Use `POST /api/v1/knowledge/ask` with an
optional `project_id` to ask across boards.

Same-origin JSON + your login cookie are required, like every mutation. Unknown project →
404; provider down → 503 (never a guess).

## Draft cards now cite their PRD passages

Plan with AI with a brief selected → **Preview cards**: each proposed card lists
"From brief passages: P1 · P3". After you approve creation, opening the card shows a
**From the brief · source passages** block with the quoted text beside the existing
whole-brief link (`source_prd_id` · revision). A model that cites a passage id that
doesn't exist gets the whole preview rejected (502, nothing written) — invented references
are never accepted.

## Chat scoping

With 📚 Library on, passages quoted into chat answers come from the selected Planning
project's documents plus workspace-wide ones — other boards' documents stay out of the
block (tested).

## Checks

```powershell
python -m pytest tests/test_knowledge.py tests/test_prds.py -q   # board/ask/citation tests included
```
