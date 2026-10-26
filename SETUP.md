# Zero Magic — approved AI actions and card discussions

## Install (Windows / existing project)

1. Back up your code or commit your current work.
2. Stop Uvicorn with Ctrl+C.
3. Extract this ZIP and copy its contents into `C:\Zero Magic Project`, merging
   the `app`, `frontend`, `tests`, and `docs` folders. Replace matching files.
   Do not delete other files in those folders.
4. Keep your existing `.env`, `.venv`, `app/main.py`, and `app/__init__.py`.
   No API keys or virtual environments are included in this ZIP.
5. Your uploaded `main.py` already registers `assistant_router`, `cards_router`,
   and `team_router`, and serves `frontend` at `/static`. No router changes needed.
6. Open a VS Code terminal using the existing `.venv` and run:

```powershell
python -m pytest -q
```

Then start the site separately:

```powershell
python -m uvicorn app.main:app --reload
```

7. Open http://127.0.0.1:8000/ and press Ctrl+F5.

IMPORTANT: this is still in-memory storage. Stopping/restarting Python clears
current cards, people, comments, and pending approvals. A code backup is NOT a
backup of running in-memory data. Browser refresh alone does not clear board data.

## Files in this update

Replace these six backend files together:
- `app/assistant.py`
- `app/llm.py`
- `app/cards.py`
- `app/schemas.py`
- `app/storage.py`
- `app/team.py`

Replace all three frontend files:
- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`

Also copy the NEW `frontend/vendor/` folder. It contains Marked 18.1.2 and
DOMPurify 3.4.17, plus their licenses. They run locally: no npm build or runtime
CDN is required. No new Python packages beyond your existing project dependencies
are required by the feature code.

Two new test files and a written feature spec are included. Keep your existing tests.
The included tests mock model replies; they do not consume Groq tokens.

## Try the AI workflow

1. Use **People** to add profiles with actual skills and responsibilities.
2. Open **Plan with AI**, describe the idea, and answer its questions.
3. Click **Preview cards**, or type exactly **deploy the plan** / **create the plan**.
   These phrases prepare a preview; they do not deploy the website or bypass approval.
4. Review each proposed card. Expand its title to see goal, acceptance criteria,
   and scope notes.
5. Click **Create N cards**. This creates that exact preview in Spec, unassigned.
6. The assistant automatically prepares assignment suggestions using current profiles.
7. Review the proposed person and reason for every card. Scroll the preview list
   to inspect every row.
8. Click **Yes, apply these assignments**, or type **yes** while that preview is pending.
9. Close the chat and inspect the board. Refresh the browser to confirm the saves.

**Change this** / **Dismiss** cancels the pending preview without undoing previously
approved operations. Discuss changes, then request a new preview.

A short typed yes approves only the currently visible pending preview in that tab.
Without one, yes is ordinary discussion, never authorization to invent an operation.
The explicit buttons are the reliable way to choose the requested action.

### If assignment suggestions fail after card creation
Your cards are already saved. Use **Suggest assignments** to retry that step.
Do NOT create the cards again. If there are no people, add profiles first.

After a page reload, typing **assign the cards** prepares suggestions for currently
unassigned, non-Done cards (up to 12). After card creation in the same conversation,
assignment suggestions target only those newly created cards.

## Discussion workflow

- Hover or keyboard-focus a card to reveal the quick-reply composer.
- On a touch device, the composer is visible without hover.
- Choose a **Posting as** profile and post a reply.
- Click the reply-count button to open the full discussion.
- Replies show the author's saved name, avatar initials, and timestamp.
- While a full thread is open, it refreshes every eight seconds. This is polling,
  not WebSocket realtime chat.
- Existing comments created before this update have no historical timestamp;
  the interface does not invent one.
- Comments remain plain text (not executable HTML).

## What makes the assistant actions safe

- Discussion responses cannot write to the board.
- Card proposals and assignment proposals are separate, validated JSON objects.
- Proposals are stored server-side; confirmation cannot replace their contents.
- Approval requires a proposal ID, its conversation ID, and explicit approval.
- The model cannot choose or invoke the confirmation endpoint.
- Replaying the same successful approval returns the original receipt rather than
  creating duplicate cards or repeating model work.
- A fresh card draft with an existing identical title is rejected. This is a
  simple duplicate guard, not semantic duplicate detection.
- Previews expire after 30 minutes. A new chat instruction supersedes older pending previews.
- Board/team changes invalidate old previews instead of silently overwriting newer work.
- A model-generated nonexistent person or out-of-scope target card is rejected.
- All items are validated before batch writes. A single-process lock and rollback
  protect the in-memory batch. Creation and assignment reuse the existing API handlers.
- Authoritative board and team context comes from the server, not from model claims.
- Model Markdown is parsed, then sanitized with an allowlist. Scripts, forms,
  images, event handlers, and unsafe links do not become executable UI.

## Boundaries (please read)

This is a LOCAL prototype, not production team collaboration:
- There is no login, role authorization, API rate limiting, or persistent audit log yet.
- A selected posting profile is a label, NOT proof of who is typing. Anyone with
  API access can choose another profile. Real team use requires authentication.
- Conversation IDs scope preview access in the local workflow; they are NOT user authentication.
- Use one Uvicorn worker. In-memory state and its lock are not shared across processes.
- Do not expose this API publicly or deploy it for a team until auth, rate limits,
  persistent storage, and proper database transactions are added.
- AI can CREATE new cards and ASSIGN approved target cards in this version.
  It cannot automatically edit/delete existing cards, change stages, run code,
  merge Git branches, or deploy your application. Existing manual controls still work.
- Replanning is conversational for now: request new follow-up cards or edit existing
  cards manually. Confirmed edits to existing plans are a later operation type.
- Proposals are immutable previews, not inline-editable drafts. Revise through chat
  and generate a new preview; manually edit saved cards if needed.
- There is a maximum of 12 cards or assignments per preview and 40 conversation
  messages, plus request-size limits. Long proposals may need to be split.
- Team skills are self-described context; suggestions are not verified skill assessments
  or an optimized workload scheduler. Review assignments yourself.
- Chat sends workspace context to your configured Groq provider and can consume quota.
  Never put passwords, keys, or confidential data in cards or chat without permission.

## Troubleshooting

- Old layout, missing buttons, or raw Markdown: Ctrl+F5. Verify all vendor files
  are under `frontend/vendor`, not nested inside another frontend folder.
- `/assistant/chat` returns 422 about `conversation_id`: replace/refresh the frontend
  and backend together; an old cached frontend uses the old request contract.
- Model service 503: check your existing `.env` and Groq account/model limits.
  Never share the API key in chat or screenshots.
- Invalid proposal 502: nothing was written. Clarify the idea, ask for fewer tasks,
  and retry. Provider JSON is validated, never blindly accepted.
- Preview 409: the board/team changed, the draft repeats a title, or a newer
  instruction superseded it. Review the error and request a fresh preview.
- Preview 410: it expired; request a fresh one.
- Confirmation response lost: retry the SAME displayed approval; it is idempotent.
- Restart clears profiles/cards: expected until the PostgreSQL milestone.

## Verification performed

The included deterministic suite tests previews without writes, explicit approvals,
separate assignment approval, repeated and concurrent confirmations, stale/expired/
cancelled proposals, invalid model output, invented people, rollback, duplicate titles,
clarification responses, profile names/timestamps, and existing API contracts.

Browser checks exercise actual local endpoints with simulated model responses:
hover/touch quick replies, second-client thread polling, inline edits, Markdown XSS
filtering, both approval stages, a deliberately lost confirmation response, refresh
persistence, stale-preview rejection, and desktop/mobile dialogs.

No paid Groq calls were made during these checks. Run the live smoke test above
with your actual key after installing, and rerun your full existing test suite.
