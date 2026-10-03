"""Weekly-run state machine.

CREATED -> AWAITING_SELECTION -> SELECTED -> SCRIPTED -> VOICED -> AWAITING_APPROVAL
        -> APPROVED -> RENDERED -> COMPOSED -> UPLOADED -> DONE

Side states: SKIPPED (no selection in time), CANCELLED (rejected by you), FAILED
(``failed_stage`` records where; ``wwnn resume`` / the Telegram Resume button moves it back).
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    CREATED = "CREATED"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    SELECTED = "SELECTED"                  # -> script writing (with pacing)
    SCRIPTED = "SCRIPTED"                  # -> TTS
    VOICED = "VOICED"                      # -> send script + audio for approval
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"                  # -> LongCat render (the expensive part)
    RENDERED = "RENDERED"                  # -> compositing
    COMPOSED = "COMPOSED"                  # -> private upload
    UPLOADED = "UPLOADED"                  # -> review checklist
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


TERMINAL = {State.DONE, State.SKIPPED, State.CANCELLED}
GATES = {State.AWAITING_SELECTION, State.AWAITING_APPROVAL}

_ALLOWED: dict[State, set[State]] = {
    State.CREATED: {State.AWAITING_SELECTION},
    State.AWAITING_SELECTION: {State.SELECTED, State.SKIPPED},
    State.SELECTED: {State.SCRIPTED},
    State.SCRIPTED: {State.VOICED, State.SELECTED},          # SELECTED = post-TTS re-pacing
    State.VOICED: {State.AWAITING_APPROVAL},
    State.AWAITING_APPROVAL: {State.APPROVED, State.SELECTED, State.CANCELLED},  # SELECTED = regenerate
    State.APPROVED: {State.RENDERED},
    State.RENDERED: {State.COMPOSED},
    State.COMPOSED: {State.UPLOADED},
    State.UPLOADED: {State.DONE},
    State.FAILED: set(State) - {State.FAILED},               # resume to failed_stage
}
for _s in State:
    if _s not in TERMINAL:
        _ALLOWED.setdefault(_s, set())
        _ALLOWED[_s] |= {State.FAILED, State.CANCELLED}


class InvalidTransition(RuntimeError):
    pass


def check_transition(old: str | State, new: str | State) -> None:
    old, new = State(old), State(new)
    if new not in _ALLOWED.get(old, set()):
        raise InvalidTransition(f"{old.value} -> {new.value} is not allowed")
