"""PRD drafts use local keys. Approval resolves keys to real card IDs."""
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Annotated
from pydantic import StringConstraints
from app.schemas import NonBlankText, CardCreate

DraftKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class PRDInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: NonBlankText = Field(max_length=150)
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=80, max_length=18000)]
    source_name: str = Field(default="Pasted brief", max_length=150)


class PRDUpdate(PRDInput):
    expected_revision: int = Field(ge=1, strict=True)


class CardDraft(CardCreate):
    key: DraftKey
    title: NonBlankText = Field(max_length=200)
    goal: NonBlankText = Field(max_length=2000)
    acceptance_criteria: list[NonBlankText] = Field(min_length=1, max_length=8)
    out_of_scope: str = Field(default="", max_length=1500)
    depends_on: list[DraftKey] = Field(default_factory=list, max_length=11)


class Breakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cards: list[CardDraft] = Field(default_factory=list, max_length=12)
    clarification: NonBlankText | None = Field(default=None, max_length=1500)

    @model_validator(mode="after")
    def validate_graph(self):
        if self.clarification is not None:
            if self.cards:
                raise ValueError("Ask a clarification OR propose cards, never both.")
            return self
        if not self.cards:
            raise ValueError("Propose 1–12 cards, or ask a focused clarification.")
        keys = [c.key for c in self.cards]
        titles = [c.title.casefold() for c in self.cards]
        if len(set(keys)) != len(keys) or len(set(titles)) != len(titles):
            raise ValueError("Card keys and titles must be unique.")
        graph = {c.key:c.depends_on for c in self.cards}
        for card in self.cards:
            if card.key in card.depends_on or len(set(card.depends_on)) != len(card.depends_on):
                raise ValueError("No self-dependencies or repeated dependencies.")
            if not set(card.depends_on) <= set(keys):
                raise ValueError("Every dependency must name a key from this draft.")
        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError("Dependencies must not contain a cycle.")
            if key in visited:
                return
            visiting.add(key)
            for dependency in graph[key]:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)
        for key in keys:
            visit(key)
        if len(json.dumps(self.model_dump(), ensure_ascii=False)) > 10000:
            raise ValueError("Draft is too large to review. Use a smaller first release.")
        return self
