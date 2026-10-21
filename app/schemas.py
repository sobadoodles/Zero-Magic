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

    title: NonBlankText
    goal: NonBlankText
    acceptance_criteria: list[NonBlankText] = Field(default_factory=list)
    out_of_scope: str = ""


class CardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonBlankText | None = None
    goal: NonBlankText | None = None
    acceptance_criteria: list[NonBlankText] | None = None
    out_of_scope: str | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_values(cls, data):
        if isinstance(data, dict):
            for field, value in data.items():
                if value is None:
                    raise ValueError(f"{field} cannot be null")

        return data