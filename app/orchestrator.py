"""The orchestrator. Routes a turn to sub-agents; never produces a value.

Routing is deterministic Python, not an LLM deciding who speaks next. The
turn's shape decides: an image goes to vision, a question about a field goes
to the explainer, "what next" goes to guidance. That costs us some
flexibility and buys two things worth more in this product:

  - the gate is unskippable. It is not a sub-agent the router can neglect to
    call; it is a line of code on the path out.
  - the demo behaves the same way every run.

The orchestrator's other job is a negative one. There is no code path here
that writes a field value into state, because there is no value in state to
write (see app/session.py). It routes, explains, and gates. The person fills
in their own form.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app import config, form_match
from app.agents import (
    confidence_gate,
    family_loop,
    field_explainer,
    guidance,
    signpost,
    vision,
)
from app.session import FormSession, store

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """One response to the client. Flat on purpose - the frontend is dumb."""

    kind: str                      # scan | explain | next | family | error
    session_id: str
    message: str = ""              # the main thing to show
    detail: Optional[str] = None   # secondary line, e.g. how to decide
    field_key: Optional[str] = None    # stable handle the client sends back
    field_label: Optional[str] = None  # display text only
    # What is actually printed on the form beside this field. Vision reads
    # both and we were discarding them, which is the one thing a confused
    # person most wants: what am I choosing between, and how do I mark it.
    field_options: List[str] = field(default_factory=list)
    field_notes: Optional[str] = None
    action: Optional[str] = None
    stopped: bool = False          # did the gate stop us
    stop_reason: Optional[str] = None
    offer_family_loop: bool = False
    confidence: float = 0.0
    # Official page for a form we do not hold guidance for. Only ever set
    # from an allowlisted government domain; see agents/signpost.py.
    authority_url: Optional[str] = None
    fields: List[Dict[str, Any]] = field(default_factory=list)
    completed: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "session_id": self.session_id,
            "message": self.message,
            "detail": self.detail,
            "field_key": self.field_key,
            "field_label": self.field_label,
            "field_options": self.field_options,
            "field_notes": self.field_notes,
            "action": self.action,
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "offer_family_loop": self.offer_family_loop,
            "confidence": round(self.confidence, 2),
            "authority_url": self.authority_url,
            "fields": self.fields,
            "completed": self.completed,
            "sources": self.sources,
        }


def _fields_payload(session: FormSession) -> List[Dict[str, Any]]:
    done = session.completed_set
    return [
        {
            "key": f.key,
            "label": f.label,
            "kind": f.kind,
            "options": f.options,
            "done": f.key in done or f.has_value,
            "notes": f.notes,
        }
        for f in session.fields
    ]


def _base(session: FormSession, kind: str) -> TurnResult:
    return TurnResult(
        kind=kind,
        session_id=session.session_id,
        fields=_fields_payload(session),
        completed=list(session.completed),
    )


def _attach_field(result: TurnResult, session: FormSession, key: Optional[str]) -> None:
    """Carry the printed options and layout note for the field in play."""
    found = session.field_by_key(key) if key else None
    if found is None:
        return
    result.field_options = list(found.options)
    result.field_notes = found.notes or None


async def _guide(
    session: FormSession, kind: str = "next", focus_label: str = ""
) -> TurnResult:
    """Ask guidance for the next step, then put it through the gate.

    Every path that ends in an instruction goes through here, so the gate
    cannot be bypassed by adding a new turn type later.
    """
    step = await guidance.next_step(
        fields=session.fields,
        completed=session.completed_set,
        last_event=session.history[-1] if session.history else "",
        form_guess=session.form_guess,
        form_id=session.form_id,
        focus_label=focus_label,
    )

    decision = confidence_gate.evaluate(
        action=step.action,
        confidence=step.confidence,
        ask_someone=step.action == "ask",
    )

    result = _base(session, kind)
    result.field_key = step.field_key
    result.field_label = step.field_label
    _attach_field(result, session, step.field_key)
    result.action = step.action
    result.confidence = step.confidence
    result.sources = step.sources
    result.stopped = decision.stopped
    result.offer_family_loop = decision.offer_family_loop

    if decision.stopped:
        result.stop_reason = decision.reason.value if decision.reason else None
        result.message = decision.message
        # The proposed step is still shown as context on an irreversible stop:
        # the user should know WHAT they are being stopped at.
        if decision.reason is confidence_gate.Stop.IRREVERSIBLE:
            result.detail = step.step or None
        session.note(f"stopped at {step.field_label or step.action}: {result.stop_reason}")
    else:
        result.message = step.step
        result.detail = step.why
        session.note(f"guided to {step.field_label or step.action}")

    store.save(session)
    return result


async def handle_scan(
    session: FormSession, image: bytes, *, image_mime: str = "image/jpeg"
) -> TurnResult:
    """Camera or screenshot turn: read the form, then guide."""
    reading = await vision.extract_fields(
        image, image_mime=image_mime, form_id=session.form_id
    )

    if reading.is_empty or reading.confidence < config.CONFIDENCE_FLOOR:
        decision = confidence_gate.evaluate(
            action="read",
            confidence=reading.confidence,
            could_read=not reading.is_empty,
        )
        result = _base(session, "scan")
        result.stopped = True
        result.stop_reason = decision.reason.value if decision.reason else None
        result.message = decision.message
        result.confidence = reading.confidence
        result.offer_family_loop = decision.offer_family_loop
        session.note("could not read the form clearly")
        store.save(session)
        return result

    # Replace the field structure wholesale - a new photo is a new reading of
    # the form - but keep what the user already told us they finished.
    session.fields = reading.fields
    session.form_guess = reading.form_guess
    session.note(f"read the form: {reading.form_guess}")
    store.save(session)

    # Do we actually hold guidance for this? The explainer refuses
    # out-of-corpus questions on its own, but guidance would still propose
    # plausible-sounding steps on a form it knows nothing about. Decide it
    # here, once, before anything is proposed.
    if not session.form_known:
        seen = form_match.match(reading.form_guess, (f.label for f in reading.fields))
        if seen.unknown:
            logger.info(
                "unrecognised form (score=%d, matched=%s): %r",
                seen.score, seen.matched, reading.form_guess,
            )
            return await _handle_unknown_form(session, reading)
        session.form_known = True
        store.save(session)

    return await _guide(session, kind="scan", focus_label=reading.focus_label or "")


async def _handle_unknown_form(session: FormSession, reading) -> TurnResult:
    """A form we hold no corpus for. Refuse to guide, then point at whoever
    is actually responsible for it.

    The signpost is the only part of SnapKaki that touches the open web, and
    it locates rather than interprets - see app/agents/signpost.py. We still
    say plainly that we will not explain this form.
    """
    decision = confidence_gate.evaluate(
        action="read", confidence=reading.confidence, known_form=False
    )

    result = _base(session, "unknown_form")
    result.stopped = True
    result.stop_reason = decision.reason.value if decision.reason else None
    result.message = decision.message
    result.confidence = reading.confidence
    result.offer_family_loop = decision.offer_family_loop

    post = await signpost.find(reading.form_guess)
    if post.useful:
        detail = f"This looks like it belongs to {post.authority}."
        if post.contact:
            detail += f" You can reach them on {post.contact}."
        result.detail = detail
        result.authority_url = post.url
    else:
        result.detail = (
            "I couldn't work out which agency issues this one either. The "
            "office you got the form from will know."
        )

    session.note(f"unrecognised form: {reading.form_guess}")
    store.save(session)
    return result


async def handle_question(
    session: FormSession,
    *,
    field_key: str,
    question: str = "",
    simple: Optional[bool] = None,
) -> TurnResult:
    """"What does this field mean?" turn.

    `simple` is sticky: the client sends it with each ask, and we keep the
    last value on the session so the preference survives a reload.
    """
    if simple is not None:
        session.simple = simple

    known = session.field_by_key(field_key)
    label = known.label if known else field_key

    explanation = await field_explainer.explain(
        label,
        question=question,
        language=session.language,
        form_id=session.form_id,
        simple=session.simple,
    )

    # An explanation is not an instruction, so the gate is consulted on a
    # softer question: is this field one a person should handle, and did we
    # actually have grounding for it?
    decision = confidence_gate.evaluate(
        action="read",
        confidence=explanation.confidence,
        ask_someone=explanation.ask_someone,
    )

    result = _base(session, "explain")
    result.field_key = known.key if known else None
    result.field_label = label
    _attach_field(result, session, known.key if known else None)
    result.confidence = explanation.confidence
    result.sources = explanation.sources
    result.offer_family_loop = decision.offer_family_loop

    if decision.stopped:
        result.stopped = True
        result.stop_reason = decision.reason.value if decision.reason else None
        # Show what we did manage to say, then the stop. On an ask_someone
        # field the explanation is the useful part and the stop is the advice.
        result.message = explanation.explanation or decision.message
        result.detail = decision.message
    else:
        result.message = explanation.explanation
        result.detail = explanation.how_to_decide

    session.note(f"explained {label}")
    store.save(session)
    return result


async def handle_field_done(session: FormSession, *, field_key: str) -> TurnResult:
    """The user says they finished a field. We record the key, not the value."""
    session.mark_complete(field_key)
    session.note(f"finished {session.label_for(field_key)}")
    store.save(session)
    return await _guide(session, kind="next")


async def handle_next(session: FormSession) -> TurnResult:
    """Plain "what now?" turn."""
    if not session.fields:
        result = _base(session, "next")
        result.message = (
            "Point your camera at the form and I'll read it — or take a "
            "screenshot if you're filling it in online."
        )
        return result
    return await _guide(session, kind="next")


# Why we stopped, phrased as the user would say it to a relative. The client
# sends the stop_reason code it was given, not prose — the card's wording is
# SnapKaki talking to the user, which reads oddly forwarded to someone else.
_STOP_PHRASES = {
    confidence_gate.Stop.IRREVERSIBLE.value:
        "It's the declaration you have to sign, and it also gives permission "
        "for income records to be checked.",
    confidence_gate.Stop.LOW_CONFIDENCE.value:
        "I'm not confident I've understood this part correctly.",
    confidence_gate.Stop.ASK_SOMEONE.value:
        "This part needs checking with you or with the agency.",
    confidence_gate.Stop.NO_READING.value:
        "I can't read this part of the form clearly.",
}


async def handle_family_loop(session: FormSession, *, stuck_on: str = "", reason: str = "") -> TurnResult:
    """Draft the message that brings a relative in. Text only, by construction.

    `stuck_on` is a field key from the client; it is resolved to a label here
    so the drafted message never contains an internal handle.
    """
    phrase = _STOP_PHRASES.get(
        reason, reason or "I'm not sure about the declaration at the end."
    )
    stuck_label = session.label_for(stuck_on) if stuck_on else ""
    summary = await family_loop.summarise(
        form_guess=session.form_guess,
        completed_labels=session.completed_labels(),
        stuck_on=stuck_label or (session.fields[-1].label if session.fields else ""),
        reason=phrase,
        language=session.language,
    )

    result = _base(session, "family")
    result.message = summary.message
    result.detail = summary.subject
    session.note("drafted a message for family")
    store.save(session)
    return result
