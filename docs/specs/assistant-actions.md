# Approved AI plans and card discussions

## Goal
Turn a planning conversation into real cards and team assignments with separate,
explicit approval, and make card discussion easy to access from the board.

## API contract
- POST /api/v1/assistant/chat
  - conversation_id: UUID
  - messages: user/assistant history
  - mode: discuss (default), plan, or assign
  - target_card_ids: required for assign, up to 12 distinct existing cards
  - Response: message, model, proposal (nullable)
- POST /api/v1/assistant/proposals/{id}/confirm
  - conversation_id and approve: true
  - Response: deterministic saved-operation receipt, including affected cards
- POST /api/v1/assistant/proposals/{id}/cancel
  - conversation_id
- Existing comment POST also accepts optional author_id; the server uses the
  profile's name when provided and attaches created_at in UTC.
- Card listing adds comment_count without mutating stored card content.

## Acceptance criteria
1. Discussion and preview generation do not change any card or assignment.
2. Confirming a card preview creates exactly those cards in Spec, unassigned.
3. Assignment suggestions appear afterward and require a separate approval.
4. Confirming the same proposal twice or concurrently returns the same receipt.
5. Unknown or wrong-conversation proposals return 404; expired previews return
   410; stale/superseded/cancelled previews return 409 without writes.
6. All proposed data is validated before a batch applies. Failed batches leave no
   partial card creation or assignment changes.
7. Nonexistent people, invalid target cards, duplicate draft titles, blank goals,
   malformed JSON, and unexpected proposal fields cannot produce writes.
8. Fresh draft titles matching existing titles are rejected rather than duplicated.
9. A vague plan may produce a clarification question instead of fabricated cards.
10. The UI shows the exact pending operation and never treats model prose as proof of a save.
11. Markdown output renders cleanly without executing model-supplied scripts/HTML controls.
12. Hover/focus reveals a quick reply, touch supports it without hover, and a full
    thread shows who posted each message and when (where recorded).
13. A second client's replies appear through polling while a thread is open.
14. Profile labels are explicitly described as unverified until authentication exists.

## Out of scope
Persistent storage, authenticated users, production authorization/rate limits,
agent execution, existing-card edits by AI, automatic stage changes, deployment,
semantic duplicate detection, workload optimization, and inline editing of proposals.
