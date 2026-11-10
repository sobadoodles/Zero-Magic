"""The card stage machine as a pure, injectable domain module.

Everything the funnel allows — and refuses — is decided here, once. Persistence
is injected: callers supply a `stage_of(card_id) -> stage | None` policy read
from whatever store backs them (SQLite dicts today, PostgreSQL next), so this
module imports no storage, no FastAPI, and performs no I/O.

`transition_error` keeps the EXACT wording the public API has always returned
(409 "Cannot move card from X to Y" / "Finish prerequisite cards first: #n"),
because the endpoint, the acting agent's staging, and 40+ existing tests all
depend on it.
"""
from typing import Callable, Optional

# The only legal moves. Done is terminal. Checks/Validation may return to
# Building when checks fail or a human sends work back.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Spec": {"Ready"},
    "Ready": {"Building"},
    "Building": {"Checks"},
    "Checks": {"Validation", "Building"},
    "Validation": {"Done", "Building"},
    "Done": set(),
}

STAGES = tuple(ALLOWED_TRANSITIONS)


def legal_next(stage: str) -> list[str]:
    """Stages reachable in one move (sorted for stable tool/API output)."""
    return sorted(ALLOWED_TRANSITIONS.get(stage, set()))


def blocked_prerequisites(card: dict, stage_of: Callable[[int], Optional[str]]) -> list[int]:
    """Prerequisite ids that are not Done. Unknown cards count as blocking —
    a dependency you cannot read is a dependency you cannot trust."""
    return [dependency_id
            for dependency_id in card.get("depends_on", [])
            if stage_of(dependency_id) != "Done"]


def transition_error(card: dict, requested_stage: str,
                     stage_of: Callable[[int], Optional[str]] = lambda _id: "Done") -> Optional[tuple[int, str]]:
    """Return (http_status, message) when the move must be refused, else None.

    The default policy assumes all prerequisites Done, so callers that do not
    model dependencies still get pure transition checking.
    """
    current_stage = card.get("stage")
    if current_stage not in ALLOWED_TRANSITIONS:
        return (409, f"Unknown current stage {current_stage!r}")
    if requested_stage not in ALLOWED_TRANSITIONS[current_stage]:
        return (409, f"Cannot move card from {current_stage} to {requested_stage}")
    if requested_stage == "Building":
        blocked = blocked_prerequisites(card, stage_of)
        if blocked:
            return (409, "Finish prerequisite cards first: "
                    + ", ".join(f"#{dependency_id}" for dependency_id in blocked))
    return None
