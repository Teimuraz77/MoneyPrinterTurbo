import pytest

from wwnn.orchestrator.state import InvalidTransition, State, check_transition

HAPPY = ["CREATED", "AWAITING_SELECTION", "SELECTED", "SCRIPTED", "VOICED", "AWAITING_APPROVAL",
         "APPROVED", "RENDERED", "COMPOSED", "UPLOADED", "DONE"]


def test_happy_path():
    for a, b in zip(HAPPY, HAPPY[1:]):
        check_transition(a, b)


@pytest.mark.parametrize("old,new", [
    ("VOICED", "APPROVED"),               # cannot skip the audio approval gate
    ("SELECTED", "APPROVED"),
    ("AWAITING_APPROVAL", "RENDERED"),    # no rendering without approval
    ("SCRIPTED", "RENDERED"),
    ("COMPOSED", "DONE"),                 # cannot skip upload verification
    ("DONE", "FAILED"),
    ("CANCELLED", "SELECTED"),
])
def test_forbidden(old, new):
    with pytest.raises(InvalidTransition):
        check_transition(old, new)


def test_gates_and_resume():
    check_transition("AWAITING_APPROVAL", "SELECTED")     # regenerate
    check_transition("AWAITING_APPROVAL", "CANCELLED")    # reject
    for s in ("SELECTED", "APPROVED", "RENDERED"):
        check_transition("RENDERED" if s == "RENDERED" else "APPROVED", "FAILED")
        check_transition("FAILED", s)                       # resume at failed stage
    assert State("APPROVED") is State.APPROVED
