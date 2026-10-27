from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    title: NonBlankText
    goal: NonBlankText
    acceptance_criteria: list[NonBlankText] = Field(default_factory=list)
    out_of_scope: str = ""


class CardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    title: NonBlankText | None = None
    goal: NonBlankText | None = None
    acceptance_criteria: list[NonBlankText] | None = None
    out_of_scope: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_values(cls, data):
        if isinstance(data, dict):
            for field, value in data.items():
                if value is None and field != "project_id":
                    raise ValueError(f"{field} cannot be null")

        return data
    
from enum import Enum
class CardStage(str, Enum):
    SPEC = "Spec"
    READY = "Ready"
    BUILDING = "Building"
    CHECKS = "Checks"
    VALIDATION = "Validation"
    DONE = "Done"


class CardStageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: CardStage


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: NonBlankText = Field(max_length=10000)


class CommentRead(BaseModel):
    id: int
    card_id: int
    author: str
    text: str
    author_id: int | None = None
    created_at: str | None = None
    user_id: int | None = None
