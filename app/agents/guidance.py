"""Guidance sub-agent: what is the ONE next thing to do?

Exactly one step, never a checklist. A person who is overwhelmed by a form
is not helped by being handed the whole form again as bullet points. The
single-step constraint is a product decision, not a prompt-economy one.

This agent also names the action kind, and that name is what the confidence
gate reads. It does not decide whether the step is allowed — see
app/agents/confidence_gate.py, which is plain Python for exactly that reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from typing import List, Optional

from google.adk.agents import LlmAgent

from app import config
from app.agents.runtime import clamp_confidence, model_name, parse_json, run_agent
from app.rag import retriever

logger = logging.getLogger(__name__)

# The vocabulary the gate matches against. Keep in sync with
# config.IRREVERSIBLE_ACTIONS - anything in that set stops the flow.
ACTION_KINDS = {
    "read",      # look at something on the form
    "enter",     # type or write a value themselves
    "choose",    # pick one of the printed options
    "check",     # verify something they already entered
    "ask",       # get a human - agency or family
    "sign",      # irreversible
    "consent",   # irreversible
    "submit",    # irreversible
    "done",      # nothing left
}

INSTRUCTION = """\
You are the guidance component of SnapKaki. Someone is filling in an
official form. You tell them the ONE next thing to do. Not a list. One step.

You will be given the form's fields, which ones are already filled, what
just happened, and retrieved guidance about this form.

Rules:

1. One step. The smallest useful one. If the next field is a table, the step
   is the first row, not the table.
2. Never supply a value. You say "find your identification card and copy the
   number across" - never the number. Values are always entered by the person.
3. Work in the printed order of the form unless a field is clearly blocked by
   an earlier one.
4. If the next thing is a signature, a consent, or a submission, say so
   honestly and name it in "action". Do not soften it and do not encourage
   it. Something downstream will stop the flow there, and it should.
5. If you are unsure what comes next - the form is unfamiliar, fields are
   missing, the state does not make sense - set a low confidence and make
   the action "ask". Guessing a next step on a legal form is worse than
   admitting you lost the thread.

Return ONLY a JSON object, no prose and no code fence:

{
  "step": "the one next thing, addressed to the person, one or two sentences",
  "field_label": "the field this step is about, or null",
  "action": one of: read, enter, choose, check, ask, sign, consent, submit, done
  "why": "one short sentence on why this step matters, or null",
  "confidence": 0.0 to 1.0
}
"""


@dataclass
class NextStep:
    step: str = ""
    field_label: Optional[str] = None
    action: str = "ask"
    why: Optional[str] = None
    confidence: float = 0.0
    sources: List[str] = dc_field(default_factory=list)


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="guidance",
        model=model_name(),
        description=(
            "Decides the single next step on a form and names the action kind "
            "so the gate can judge it."
        ),
        instruction=INSTRUCTION,
    )


_agent: Optional[LlmAgent] = None


def _get_agent() -> LlmAgent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def _render_fields(fields, completed: set[str]) -> str:
    if not fields:
        return "(no fields read from the form yet)"
    lines = []
    for f in fields:
        mark = "x" if (f.label in completed or f.has_value) else " "
        opts = f" options: {', '.join(f.options)}" if f.options else ""
        lines.append(f"  [{mark}] {f.label} ({f.kind}){opts}")
    return "\n".join(lines)


async def next_step(
    *,
    fields,
    completed: set[str],
    last_event: str = "",
    form_guess: str = "",
    form_id: str = config.DEMO_FORM_ID,
) -> NextStep:
    """Pick the next step. Never raises; failure comes back as low confidence."""
    remaining = [f for f in fields if f.label not in completed and not f.has_value]
    query = remaining[0].label if remaining else "finishing the form declaration"
    chunks = retriever.retrieve(query, k=2, form_id=form_id)
    sources = [c.heading for c in chunks]

    if config.USE_STUB:
        return _stub_step(remaining, sources)

    prompt = (
        f"FORM: {form_guess or 'unknown form'}\n\n"
        f"FIELDS (x = already filled):\n{_render_fields(fields, completed)}\n\n"
        f"WHAT JUST HAPPENED: {last_event or '(start of the session)'}\n\n"
        f"GUIDANCE:\n{retriever.as_context_block(chunks)}\n"
    )
    raw = await run_agent(_get_agent(), prompt)
    payload = parse_json(raw, where="guidance")

    if not payload:
        return NextStep(
            step="I've lost track of where we are. Let's take another photo of the form.",
            action="ask",
            confidence=0.0,
            sources=sources,
        )

    action = str(payload.get("action", "ask")).strip().lower()
    if action not in ACTION_KINDS:
        # An unrecognised action is not safe to act on. Treat it as "ask" and
        # drop confidence so the gate stops us.
        logger.warning("guidance returned unknown action %r", action)
        action = "ask"
        payload["confidence"] = 0.0

    why = payload.get("why")
    field_label = payload.get("field_label")
    return NextStep(
        step=str(payload.get("step", "")).strip(),
        field_label=str(field_label).strip() if field_label else None,
        action=action,
        why=str(why).strip() if why else None,
        confidence=clamp_confidence(payload.get("confidence")),
        sources=sources,
    )


def _stub_step(remaining, sources) -> NextStep:
    """Offline stand-in that still walks the real CHAS field order."""
    if not remaining:
        return NextStep(
            step="Everything above is filled in. The last thing on this form is "
                 "the declaration and signature.",
            field_label="Declaration and Consent (Clause 11)",
            action="sign",
            why="It is a legal declaration about everything you entered.",
            confidence=0.9,
            sources=sources,
        )
    nxt = remaining[0]
    if nxt.kind == "signature":
        return NextStep(
            step=f"The next part is {nxt.label}.",
            field_label=nxt.label,
            action="sign",
            why="It is a legal declaration about everything you entered.",
            confidence=0.9,
            sources=sources,
        )
    action = "choose" if nxt.options else "enter"
    return NextStep(
        step=f"[stub] Next: {nxt.label}. "
             + (f"Pick one of: {', '.join(nxt.options)}." if nxt.options else
                "Fill this one in yourself."),
        field_label=nxt.label,
        action=action,
        why=None,
        confidence=0.87,
        sources=sources,
    )
