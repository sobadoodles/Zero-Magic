# Zero Magic — smaller comments, real accounts, saved work

This is a coordinated backend/frontend update. It replaces `app/main.py` too.
Keep your existing `.env` (Groq key and model IDs), `.venv`, Git history, and any
unrelated files. Do not put your API key in the frontend.

## 1. Preserve the old running workspace FIRST

**Do not copy Python files into your project yet.** Uvicorn's `--reload` can
restart the old app when a `.py` file changes. The old app loses its in-memory
cards, people, and comments on restart.

Extract this ZIP OUTSIDE the project, for example to:

```text
C:\Zero-Magic-Update
```

Make sure that folder contains `app`, `frontend`, `scripts`, and this guide.
Leave the OLD server running. Open a second PowerShell terminal and run:

```powershell
python "C:\Zero-Magic-Update\scripts\export_old_workspace.py" --output "C:\Zero-Magic-Update\workspace-export.json"
```

This uses only Python's standard library. The export is private: it contains
card text, team profiles, and comments, but no Groq key or passwords. Verify the
reported counts and open the JSON to check your important work is there. Do not
post it to GitHub. A previous export isn't overwritten; choose another output
filename if needed.

If the old server already restarted, its previous in-memory data cannot be
recovered by this update. If you have nothing to keep, skip export/import.

## 2. Stop the old server and replace matching files

1. In the server terminal, press **Ctrl+C**.
2. Commit your current code or make a private backup of the project folder.
3. Merge the ZIP's `app`, `frontend`, `scripts`, and `tests` folders into
   `C:\Zero Magic Project`, replacing matching files. Do not delete unrelated files.
4. In particular, replace **`app/main.py`** and **`tests/conftest.py`**. The new
   main registers authentication and request protections. The new conftest
   selects a disposable test database before application imports.
5. Copy the whole `frontend/vendor` folder too. It keeps AI Markdown local.
6. Keep `.env` and `.venv` unchanged. No new environment folder is needed.

From the project root, with `.venv` active:

```powershell
.\scripts\ignore-private-files.ps1
```

This appends private data/backup/export ignore rules without replacing your
existing `.gitignore`. If PowerShell blocks scripts, run the rules manually
from `scripts/ignore-private-files.ps1`, or use your existing process-only
execution-policy setting. Check `git status` before committing; never commit
`.env`, exports, backups, or database files. Ignore rules do not untrack a file
that was already committed.

## 3. Import old work BEFORE creating your login

Keep the server stopped. If you exported old data:

```powershell
python scripts/import_workspace.py "C:\Zero-Magic-Update\workspace-export.json"
```

Import accepts an EMPTY database only and refuses to overwrite existing work.
It retains card/person IDs, stages, assignments, and historical comments.
Historical comments are labeled **Legacy comment**: their old profile labels
were not authenticated accounts.

Do not import after setting up the owner. If you accidentally started a new
workspace first, stop and ask for help merging it rather than deleting data.

## 4. Launch and create your owner login

```powershell
python -m uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/** and press **Ctrl+F5**.

- The first visit asks you to create the owner account.
- Choose a username and a unique password/passphrase of 12–128 characters.
- If you imported people, select your existing profile in **Your existing team
  profile**. This keeps your old assignments connected instead of duplicating you.
- Setup locks after the first account. Other people need an invitation.
- Use the SAME host consistently: localhost and 127.0.0.1 have different cookies.
- A normal browser remembers the login for up to 30 days. Sign out on shared
  computers. Private browsing/cookie deletion or expiry requires signing in again.

The account is local to this application, not your GitHub/Google account. The
Groq API key is separate from the password you choose here.

## 5. Invite a teammate

1. **People → Add a person**, including skills and responsibilities.
2. Click **Invite** beside the profile.
3. Share the private invitation link with that person.
4. They choose their own username/password; the login links to that same profile.

Invitation links work once, expire after 48 hours, and are replaced if you
create another link. They are not sent by email automatically.

**Localhost only reaches this computer.** For a two-user demo on one computer,
open the invitation in another browser/private window so accounts don't switch
in your own tab. Separate devices need a properly configured shared server;
this ZIP does not deploy or host the app for you. Keep it bound to localhost
for now. Do not share passwords or your Groq key with teammates.

Owner: manages people and invitations. Members: edit their own skills/profile;
all signed-in members can work on the shared board and use the AI workflow.
There are no private projects or per-card access rules in this version.

## 6. What changed on the board

- Cards have a small comment icon/count. No large textarea, identity dropdown,
  Reply button, or Posted banner on every card — even on touch screens.
- Click the badge to open the conversation and a compact comment composer.
- The signed-in name appears automatically. The server, not a submitted name,
  determines the author. Old clients trying to set `author`/`author_id` get 422.
- Thread messages retain author IDs and timestamps; new comments use real accounts.
- Open threads still refresh every 8 seconds. Board-wide live collaboration is
  not implemented; use Refresh to get others' card changes.
- Inline edits, stages, assignment, sanitized AI Markdown, and separate AI
  creation/assignment approvals are retained.

## 7. Where the data lives

By default:

```text
C:\Zero Magic Project\data\zero_magic.sqlite3
```

SQLite is a real local database, included with Python; no separate database
server or paid service is needed. Tables hold cards, people, comments, accounts,
sessions, invitations, ID counters, and AI approval receipts/proposals. Card,
profile, comment, and proposal payloads are stored as JSON records within their
SQLite tables. Approval batches and receipts commit together. Passwords use
salted scrypt hashes; session/invitation tokens are stored as hashes.

You can inspect a COPY with a SQLite viewer. Do not manually change the live
file while the app runs. It is private and not encrypted at rest.

Stopping/restarting Python no longer clears cards, team members, comments,
accounts, or approved-operation receipts. A repeated approval returns its
existing receipt rather than creating duplicates, including after restart.

The AI conversation transcript is still in browser-tab memory and resets on
reload. That is separate from saved board data. Pending previews expire after
30 minutes and are bound to the logged-in account and conversation.

**Exactly one Uvicorn worker.** This small-workspace implementation uses
in-process snapshots with atomic SQLite transactions. Do not run multiple
workers/server processes or run the import/recovery tools while the server is
running. Multi-worker/cloud deployment needs a different repository design.

## 8. Backups and recovery

From the project root:

```powershell
python scripts/backup_database.py
```

The SQLite backup API creates a consistent private backup in `backups/`, even
if the local app is running. Backups include password hashes and sessions.
Store them privately outside Git; losing/deleting the database loses your work.

To restore, stop ALL app processes. Save your current database and its matching
`-wal`/`-shm` sidecars together in a private recovery folder first. Put a chosen
backup at `data/zero_magic.sqlite3` with no stale WAL/SHM files alongside it, then
restart. Never combine a restored DB with an old WAL. Restoring also restores
sessions as they were at backup time; reset passwords to revoke those sessions
if needed. Ask for help if uncertain before overwriting anything.

Forgot a local password? With the server STOPPED:

```powershell
python scripts/reset_password.py
```

Enter the username, then the new password privately at the terminal prompts.
The script revokes previous sessions for that account. This is local recovery
for someone with access to the project/database, not an email-reset service.

## 9. Run the new checks

```powershell
python -m pytest tests/test_persistent_workspace.py -q
```

The included conftest selects a temporary database, not your real workspace.
27 tests cover authentication, cookies, owner/member permissions, spoofing
rejection, CSRF guards, one-use invitations, CRUD rules, transactional rollback,
account-scoped AI approvals, idempotency/concurrency, actual process restart,
legacy import, and backup integrity. Model calls are mocked; no key or paid
provider call is used during these tests.

Older unauthenticated tests are not drop-in compatible: protected endpoints now
return 401 until signed in, and comments accept `{"text":"..."}` only. Keep
those tests, but update their setup to create/sign in an owner and their comment
payloads to match. Old in-memory reset fixtures/counters also need updating;
use the new test suite's isolated DB setup as the example. A full old-suite run
may fail until these deliberate API changes are reflected in its tests.

## Scope and security limits

This adds real local authentication, not just a remembered display name. It
also has hashed passwords, HttpOnly SameSite cookies, revocable sessions,
persistent failed-login throttling, same-origin JSON mutation checks, trusted
host checks, and account-scoped approvals. It is still an internship/local
prototype — NOT a production security audit or internet-ready deployment.

Before hosting externally: HTTPS, Secure cookies (`COOKIE_SECURE=true`), explicit
trusted `ALLOWED_HOSTS`, proxy settings, robust account administration/recovery,
security review, shared transactional storage for workers, backups, and deployment
configuration are needed. Don't expose this localhost development server to the
internet or change security requirements just to bypass an error.

AI still creates NEW cards and proposes assignments only after your approvals.
AI edits to existing cards, deletes, stage moves, code execution/deployment,
automatic replanning of existing work, and saved AI chat transcripts are not
added by this update. Workspace context still goes to your configured Groq model.
