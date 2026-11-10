from fastapi import APIRouter, Depends, HTTPException, status
from app.auth import require_user

from app import storage, team
from datetime import datetime, timezone

from app.schemas import (
    CardCreate,
    CardStageUpdate,
    CardUpdate,
    CommentCreate,
    CommentRead,
)

router = APIRouter(prefix="/api/v1/cards", tags=["Cards"], dependencies=[Depends(require_user)])

# Week 5 three-tier: the rules moved to app/domain/card_state.py; these names
# are re-exported so existing consumers (assistant staging, tests) are unchanged.
from app.domain.card_state import ALLOWED_TRANSITIONS, legal_next, transition_error  # noqa: E402


def _stage_of(card_id):
    card = storage.cards.get(card_id)
    return card["stage"] if card else None

@router.post("", status_code=status.HTTP_201_CREATED)
@storage.synchronized
def create_card(payload: CardCreate):
    from app.projects import validate_project
    validate_project(payload.project_id)
    card_id = next(storage.card_ids)

    card = {
        **payload.model_dump(),
        "id": card_id,
        "stage": "Spec",
        "assignee": None,
        "depends_on": [],
    }

    storage.cards[card_id] = card
    return card


@router.get("")
@storage.synchronized
def list_cards():
    return [
        {**card, "comment_count": sum(
            comment["card_id"] == card["id"]
            for comment in storage.comments.values()
        )}
        for card in storage.cards.values()
    ]


@router.get("/{card_id}")
@storage.synchronized
def get_card(card_id: int):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    return card


@router.patch("/{card_id}")
@storage.synchronized
def update_card(card_id: int, payload: CardUpdate):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = payload.model_dump(exclude_unset=True)
    if "project_id" in updates:
        from app.projects import validate_project
        validate_project(updates["project_id"])
    card.update(updates)

    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
@storage.synchronized
def delete_card(card_id: int):
    if card_id not in storage.cards:
        raise HTTPException(status_code=404, detail="Card not found")

    # Remove this card from other cards' prerequisite lists.
    # Keep the other cards and their remaining prerequisites.
    for other_card in storage.cards.values():
        dependencies = other_card.get("depends_on", [])
        if card_id in dependencies:
            other_card["depends_on"] = [
                dependency_id
                for dependency_id in dependencies
                if dependency_id != card_id
            ]

    del storage.cards[card_id]

    # Delete this card's discussion too.
    comment_ids = [
        comment_id
        for comment_id, comment in storage.comments.items()
        if comment["card_id"] == card_id
    ]
    for comment_id in comment_ids:
        del storage.comments[comment_id]

    # Clear cached operations referring to the deleted card.
    from app.projects import purge_proposals
    purge_proposals({card_id}, set(), None)


@router.post(
    "/{card_id}/comments",
    status_code=status.HTTP_201_CREATED,
    response_model=CommentRead,
)
@storage.synchronized
def add_comment(card_id: int, payload: CommentCreate, user=Depends(require_user)):
    if card_id not in storage.cards:
        raise HTTPException(
            status_code=404,
            detail="Card not found",
        )

    comment_id = next(storage.comment_ids)

    comment = {
        **payload.model_dump(),
        "id": comment_id,
        "card_id": card_id,
        "author": team.people[user["person_id"]]["name"],
        "author_id": user["person_id"],
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    storage.comments[comment_id] = comment
    return comment


@router.get(
    "/{card_id}/comments",
    response_model=list[CommentRead],
)
@storage.synchronized
def list_comments(card_id: int):
    if card_id not in storage.cards:
        raise HTTPException(
            status_code=404,
            detail="Card not found",
        )

    return [
        comment
        for comment in storage.comments.values()
        if comment["card_id"] == card_id
    ]

@router.patch("/{card_id}/stage")
@storage.synchronized
def change_card_stage(card_id: int, payload: CardStageUpdate):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    requested_stage = payload.stage.value
    refusal = transition_error(card, requested_stage, stage_of=_stage_of)
    if refusal is not None:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])

    card["stage"] = requested_stage
    return card