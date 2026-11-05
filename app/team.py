from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app import storage
from app.auth import require_user, require_admin
from app.schemas import NonBlankText


router = APIRouter(prefix="/api/v1", tags=["People"], dependencies=[Depends(require_user)])
people = storage.people


class PersonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonBlankText = Field(max_length=100)
    skills: list[NonBlankText] = Field(default_factory=list, max_length=30)
    responsibility: str = Field(default="", max_length=2000)


class PersonRead(PersonInput):
    id: int
    has_login: bool = False


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required key; explicit null means unassign.
    person_id: int | None = Field(ge=1, strict=True)


@router.get("/people", response_model=list[PersonRead])
@storage.synchronized
def list_people():
    with storage.connection() as db:
        linked = {row[0] for row in db.execute("SELECT person_id FROM users")}
    return [{**person, "has_login": person["id"] in linked} for person in people.values()]


@router.post(
    "/people",
    status_code=status.HTTP_201_CREATED,
    response_model=PersonRead,
)
@storage.synchronized
def add_person(payload: PersonInput, user=Depends(require_admin)):
    person_id = next(storage.person_ids)
    person = {"id": person_id, **payload.model_dump()}
    people[person_id] = person
    return person


@router.put("/people/{person_id}", response_model=PersonRead)
@storage.synchronized
def update_person(person_id: int, payload: PersonInput, user=Depends(require_user)):
    if not user["is_admin"] and user["person_id"] != person_id:
        raise HTTPException(403, "Only the owner or this person can edit this profile.")
    if person_id not in people:
        raise HTTPException(status_code=404, detail="Person not found")
    person = {"id": person_id, **payload.model_dump()}
    people[person_id] = person
    with storage.connection() as db:
        has_login = db.execute("SELECT 1 FROM users WHERE person_id=?", (person_id,)).fetchone() is not None
    return {**person, "has_login": has_login}


@router.patch("/cards/{card_id}/assignee")
@storage.synchronized
def assign_person(card_id: int, payload: AssignmentInput):
    card = storage.cards.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    if payload.person_id is None:
        card["assignee"] = None
    else:
        if payload.person_id not in people:
            raise HTTPException(status_code=404, detail="Person not found")
        card["assignee"] = {
            "kind": "human",
            "identifier": str(payload.person_id),
        }

    return card
