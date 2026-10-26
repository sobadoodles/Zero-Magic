# Feature: Card comments

## Goal
Let someone add comments to a card and read its discussion.

## Endpoints
POST /api/v1/cards/{card_id}/comments
GET /api/v1/cards/{card_id}/comments

## Comment input
- author: required non-blank string
- text: required non-blank string
- Trim surrounding whitespace from both fields.
- Reject unexpected fields.

Author is an unverified label for now, not an authenticated identity.

## Comment response
- id: server-generated integer
- card_id: the card this comment belongs to
- author: trimmed author label
- text: trimmed comment text

## Acceptance criteria
1. Adding a valid comment to an existing card returns 201.
2. Each comment receives a unique ID.
3. Listing comments returns 200 and only that card's comments,
   in creation order.
4. A card with no comments returns an empty list.
5. Adding or listing comments on a missing card returns 404.
6. Missing, blank, or invalid input returns 422.
7. Rejected input does not save a comment.
8. Deleting a card also deletes its comments.

## Out of scope
- Editing or individually deleting comments
- Authentication and permissions
- Database persistence