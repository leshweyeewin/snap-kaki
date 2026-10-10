"""The gate is the product's core safety claim, so it gets the real tests.

These pass with no network and no model. That is the point: if the gate
needed a model to be tested, it would need a model to be trusted.
"""
import pytest

from app import config
from app.agents.confidence_gate import Stop, evaluate


@pytest.mark.parametrize("action", sorted(config.IRREVERSIBLE_ACTIONS))
def test_irreversible_actions_always_stop(action):
    """Even at full confidence. This is the demo's key beat."""
    decision = evaluate(action=action, confidence=1.0)
    assert decision.stopped
    assert decision.reason is Stop.IRREVERSIBLE
    assert decision.offer_family_loop


def test_irreversible_wins_over_low_confidence():
    """A signature is reported as a signature, not as 'I'm unsure'."""
    decision = evaluate(action="sign", confidence=0.0)
    assert decision.reason is Stop.IRREVERSIBLE


def test_unreadable_image_wins_over_everything():
    decision = evaluate(action="sign", confidence=1.0, could_read=False)
    assert decision.reason is Stop.NO_READING
    # Nothing to loop a relative in about yet - we have not read the form.
    assert not decision.offer_family_loop


def test_confidence_below_floor_stops():
    decision = evaluate(action="enter", confidence=config.CONFIDENCE_FLOOR - 0.01)
    assert decision.stopped
    assert decision.reason is Stop.LOW_CONFIDENCE


def test_confidence_at_floor_passes():
    """The floor is inclusive. Guards against an off-by-one that would make
    the gate fire on every well-understood field."""
    decision = evaluate(action="enter", confidence=config.CONFIDENCE_FLOOR)
    assert decision.allow
    assert decision.reason is None


def test_ask_someone_stops_a_confident_step():
    decision = evaluate(action="enter", confidence=0.99, ask_someone=True)
    assert decision.stopped
    assert decision.reason is Stop.ASK_SOMEONE
    assert decision.offer_family_loop


def test_ordinary_confident_step_is_allowed():
    decision = evaluate(action="choose", confidence=0.9)
    assert decision.allow
    assert not decision.stopped
    assert decision.message == ""


def test_action_matching_is_case_and_space_insensitive():
    """A model that answers " Sign " must not slip past the frozen set."""
    assert evaluate(action="  SIGN ", confidence=1.0).stopped


def test_unknown_action_with_good_confidence_is_allowed():
    """The gate judges irreversibility, not vocabulary. Unknown action names
    are normalised upstream in guidance.py, which floors their confidence."""
    assert evaluate(action="wiggle", confidence=0.9).allow


def test_irreversible_message_names_the_action():
    assert "Signing this" in evaluate(action="sign", confidence=1.0).message
    assert "Submitting this form" in evaluate(action="submit", confidence=1.0).message


def test_family_prompt_forbids_handing_over_the_pen():
    """The family message must not propose that the relative sign instead.

    The gate has just stopped the user from signing something they did not
    understand; a draft that asks someone else to sign undoes that. Asserted
    on the prompt because the behaviour is prompt-enforced, so a future edit
    that drops the rule fails here.
    """
    from app.agents.family_loop import INSTRUCTION

    text = INSTRUCTION.lower()
    assert "never ask the relative to sign" in text
    assert "representative" in text
