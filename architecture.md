# Architecture — Weeks 1–2

## Goal
Build a FastAPI backend for managing work cards, comments,
and assignment through a controlled development workflow.

## Scope
- Create, list, read, update, and delete cards.
- Validate request and response data.
- Enforce card-stage transitions.
- Add and list comments.
- Assign a card to one human or agent.
- Store data in memory.
- Test behavior with pytest.

## Out of scope
- Frontend
- Database and persistence
- Authentication and full user management
- Automated coding-agent runner
- Deployment

## Request lifecycle
Client → FastAPI route → input validation → application rules
→ in-memory storage → response

The client can initially be FastAPI's interactive /docs page.

## Card data
- id: server-generated integer
- title: required, non-empty text
- goal: required, non-empty text
- acceptance_criteria: list of non-empty strings; initially optional
- out_of_scope: optional text
- stage: defaults to Spec
- assignee: optional; one human or agent

Assignee:
- kind: human or agent
- identifier: non-empty text

Identifiers are labels for now, not authenticated identities.

## Comment data
- id: server-generated integer
- card_id: an existing card's ID
- author: non-empty identifier
- text: non-empty text

## Proposed stage transitions
- Spec → Ready
- Ready → Building
- Building → Checks
- Checks → Validation
- Checks → Building, when checks fail
- Validation → Done
- Validation → Building, when sent back

Done is terminal for this version.
All other transitions are rejected.

These rules model the workflow only. This version does not
verify CI results, pull requests, merges, or human approval.

## API endpoints
- POST   /api/v1/cards
- GET    /api/v1/cards
- GET    /api/v1/cards/{card_id}
- PATCH  /api/v1/cards/{card_id}
- PATCH  /api/v1/cards/{card_id}/stage
- DELETE /api/v1/cards/{card_id}
- POST   /api/v1/cards/{card_id}/comments
- GET    /api/v1/cards/{card_id}/comments

The general card-update endpoint cannot change the stage.
Stage changes must use the dedicated endpoint.

## Response rules
- 201: card or comment created
- 200: successful read or update
- 204: card deleted; no response body
- 404: card does not exist
- 409: stage transition is not allowed
- 422: request data is invalid

## Storage limitations
Data is lost when the application restarts.
Use one application process while storage is in memory.
Deleting a card also deletes its comments.