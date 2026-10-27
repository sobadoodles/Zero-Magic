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
ALLOWED_TRANSITIONS = {
    "Spec": {"Ready"},
    "Ready": {"Building"},
    "Building": {"Checks"},
    "Checks": {"Validation", "Building"},
    "Validation": {"Done", "Building"},
    "Done": set(),
}

@router.post("", status_code=status.HTTP_201_CREATED)
@storage.synchronized
def create_card(payload: CardCreate):
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
    card.update(updates)

    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
@storage.synchronized
def delete_card(card_id: int):
    dependents = [c["id"] for c in storage.cards.values() if card_id in c.get("depends_on",[])]
    if dependents:
        raise HTTPException(409, "Other cards depend on this card: " + ", ".join(map(str,dependents)))
    card = storage.cards.pop(card_id, None)

    if card is None:
        raise HTTPException(
            status_code=404,
            detail="Card not found",
        )

    comment_ids_to_delete = [
        comment_id
        for comment_id, comment in storage.comments.items()
        if comment["card_id"] == card_id
    ]

    for comment_id in comment_ids_to_delete:
        del storage.comments[comment_id]
@router.patch("/{card_id}/stage")
@storage.synchronized
def change_card_stage(card_id: int, payload: CardStageUpdate):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(
            status_code=404,
            detail="Card not found",
        )

    current_stage = card["stage"]
    requested_stage = payload.stage.value

    if requested_stage not in ALLOWED_TRANSITIONS[current_stage]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot move card from {current_stage} "
                f"to {requested_stage}"
            ),
        )

    if requested_stage == "Building":
        blocked = [ident for ident in card.get("depends_on",[]) if storage.cards.get(ident,{}).get("stage") != "Done"]
        if blocked:
            raise HTTPException(409, "Finish prerequisite cards first: " + ", ".join(f"#{i}" for i in blocked))
    card["stage"] = requested_stage
    return card


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