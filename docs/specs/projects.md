# Projects and deletion contract

Project = UUID id, unique casefolded name (1–80 chars), palette color, creator ID and timestamps.
GET/POST /api/v1/projects; PUT /{id}: creator/workspace-owner only.
Colors: indigo, blue, teal, green, amber, orange, pink, purple.
CardCreate/CardUpdate and PRDInput add nullable project_id. Existence is server-validated.
Existing records missing project_id are treated as Ungrouped; no inference/migration guessing.
Card previews freeze a server-selected project; confirm ignores model-provided project IDs.
New PRD cards inherit the brief project. Existing source cards do not move implicitly.

DELETE /api/v1/cards/{id} removes card/comments, purges related cached operations, rejects external dependents.
POST /api/v1/projects/{id}/deletion-preview (JSON {}): creator/owner, no deletion.
Response = token, 600-second expiry, project name, exact card IDs/titles, brief IDs/titles, comment count.
POST /api/v1/projects/deletions/{token}/confirm = {approve:true,confirm_name:exact_name}.
No direct DELETE project route; no chat-only 'yes' deletion.

Server validates actor, expiry, unchanged target snapshot, and outside references. Outside dependent/source cards block deletion. One transaction removes target cards/comments/project/associated briefs/revisions and related proposals. Keep a minimal idempotent receipt without deleted task/brief text. Foreign projects/people/accounts remain.
All API mutations retain same-origin JSON guards. Local single-worker SQLite assumptions remain.
UI command 'delete project Exact name' / 'delete this project' opens a review, never directly deletes. Model output is not an executable deletion instruction.
SQL deletion is active-record removal, not secure erasure of backups, WAL, remote requests or old client caches.
