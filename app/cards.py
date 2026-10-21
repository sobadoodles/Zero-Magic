from fastapi import APIRouter, HTTPException, status

from app import storage
from app.schemas import CardCreate, CardStageUpdate, CardUpdate

router = APIRouter(prefix="/api/v1/cards", tags=["Cards"])
ALLOWED_TRANSITIONS = {
    "Spec": {"Ready"},
    "Ready": {"Building"},
    "Building": {"Checks"},
    "Checks": {"Validation", "Building"},
    "Validation": {"Done", "Building"},
    "Done": set(),
}

@router.post("", status_code=status.HTTP_201_CREATED)
def create_card(payload: CardCreate):
    card_id = next(storage.card_ids)

    card = {
        **payload.model_dump(),
        "id": card_id,
        "stage": "Spec",
        "assignee": None,
    }

    storage.cards[card_id] = card
    return card


@router.get("")
def list_cards():
    return list(storage.cards.values())


@router.get("/{card_id}")
def get_card(card_id: int):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    return card


@router.patch("/{card_id}")
def update_card(card_id: int, payload: CardUpdate):
    card = storage.cards.get(card_id)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = payload.model_dump(exclude_unset=True)
    card.update(updates)

    return card


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(card_id: int):
    card = storage.cards.pop(card_id, None)

    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

@router.patch("/{card_id}/stage")
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

    card["stage"] = requested_stage
    return card