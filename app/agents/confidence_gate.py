"""The confidence gate. Deliberately NOT a model.

Every other sub-agent here is an LlmAgent. This one is plain Python, and
that is the most important design decision in the project.

"SnapKaki never auto-submits and stops when it is unsure" is either a
guarantee or it is marketing. A prompt that says "always stop before a
signature" can be argued out of stopping — by a confusing form, an
unusual phrasing, a user who insists, or just sampling. A function that
returns `allow=False` when the action is in a frozen set cannot.

So the gate is a pure function of (action, confidence). No model call, no
network, no prompt. It is unit-testable, it behaves identically every run,
and the demo's key beat depends on it firing reliably.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app import config


class Stop(str, Enum):
    """Why the gate stopped. Drives the wording the user sees."""

    IRREVERSIBLE = "irreversible_action"
    LOW_CONFIDENCE = "low_confidence"
    NO_READING = "no_reading"
    ASK_SOMEONE = "ask_someone"


@dataclass
class GateDecision:
    allow: bool
    reason: Optional[Stop] = None
    message: str = ""
    # Whether to offer the family-loop handoff. True for the stops where
    # another person is the actual answer.
    offer_family_loop: bool = False
    confidence: float = 0.0
    action: str = ""

    @property
    def stopped(self) -> bool:
        return not self.allow


# Wording for each stop. Kept here rather than in the frontend so the reason
# a step was blocked and the words shown to the user cannot drift apart.
_MESSAGES = {
    Stop.IRREVERSIBLE: (
        "This one I'm not going to walk you through. {action_phrase} is a legal "
        "declaration — you're confirming everything above is true, and "
        "giving permission for your income records to be checked. That's worth "
        "being sure about, not quick about."
    ),
    Stop.LOW_CONFIDENCE: (
        "I'm not confident enough about this to tell you what to do. I'd rather "
        "say that than guess on a form that matters."
    ),
    Stop.NO_READING: (
        "I couldn't read that clearly enough to help. Try again with more light, "
        "or hold the phone steadier over the part you're stuck on."
    ),
    Stop.ASK_SOMEONE: (
        "This one genuinely needs a person — either someone in your family "
        "or the agency itself. I don't want to guess at it."
    ),
}

_ACTION_PHRASES = {
    "sign": "Signing this",
    "consent": "Giving this consent",
    "submit": "Submitting this form",
    "agree": "Agreeing to this",
    "confirm": "Confirming this",
    "pay": "Making this payment",
}


def evaluate(
    *,
    action: str,
    confidence: float,
    ask_someone: bool = False,
    could_read: bool = True,
) -> GateDecision:
    """Decide whether a proposed next step may be shown as an instruction.

    Checked in order of severity, so an irreversible action is reported as
    such even when confidence is also low.
    """
    action = (action or "").strip().lower()

    if not could_read:
        return GateDecision(
            allow=False,
            reason=Stop.NO_READING,
            message=_MESSAGES[Stop.NO_READING],
            offer_family_loop=False,
            confidence=confidence,
            action=action,
        )

    if action in config.IRREVERSIBLE_ACTIONS:
        phrase = _ACTION_PHRASES.get(action, "This step")
        return GateDecision(
            allow=False,
            reason=Stop.IRREVERSIBLE,
            message=_MESSAGES[Stop.IRREVERSIBLE].format(action_phrase=phrase),
            offer_family_loop=True,
            confidence=confidence,
            action=action,
        )

    if ask_someone:
        return GateDecision(
            allow=False,
            reason=Stop.ASK_SOMEONE,
            message=_MESSAGES[Stop.ASK_SOMEONE],
            offer_family_loop=True,
            confidence=confidence,
            action=action,
        )

    if confidence < config.CONFIDENCE_FLOOR:
        return GateDecision(
            allow=False,
            reason=Stop.LOW_CONFIDENCE,
            message=_MESSAGES[Stop.LOW_CONFIDENCE],
            offer_family_loop=True,
            confidence=confidence,
            action=action,
        )

    return GateDecision(allow=True, confidence=confidence, action=action)
