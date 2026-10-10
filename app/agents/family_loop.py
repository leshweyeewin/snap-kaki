"""Family-loop sub-agent: writes the message that pulls a relative in.

Two hard constraints, both enforced in code rather than asked for in a prompt:

1. Text only, never an image. This function's signature cannot accept an
   image. The screenshot of a half-filled form - with an identification
   number visible on it - is exactly what must not be forwarded to a
   WhatsApp thread. Making it unrepresentable beats remembering not to.

2. The summary passes through `assert_clean` on the way out. The input is
   already redacted field labels, but the output is the one artifact that
   leaves the system toward another human, so it is checked again there.

SnapKaki does not send this message. It drafts it and hands it to the user,
who sends it themselves. Nothing here touches a messaging API.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from google.adk.agents import LlmAgent

from app import config
from app.agents.runtime import model_name, parse_json, run_agent
from app.redaction import assert_clean

logger = logging.getLogger(__name__)

INSTRUCTION = """\
You are the family-loop component of SnapKaki. Someone has been filling in
an official form and has hit a point where they need a relative's help. You
draft the message they can send to that relative.

You will be given which form it is, how far they got, and what stopped them.

Write it as the person themselves would send it - first person, plain,
unembarrassed. The tone matters: asking for help with a form is not an
admission of incompetence, and the message should not read like one.

Rules:
1. Never include an identification number, address, phone number, or date of
   birth, even if you were given one. Refer to fields by name only - "the
   identification number field", not the number.
2. Say specifically where they got to and what the sticking point is, so the
   relative knows what is being asked of them before they arrive.
3. If the sticking point is a signature or a consent clause, say so plainly.
   The relative needs to know this is the legally significant part.
4. Short. Four sentences at most. This is a WhatsApp message, not a letter.
5. No pleasantries padding the front. Get to it.

Return ONLY a JSON object, no prose and no code fence:

{
  "message": "the message, ready to send",
  "subject": "a 5-8 word summary for a notification line"
}
"""


@dataclass
class FamilySummary:
    message: str = ""
    subject: str = ""
    # True when we fell back to the template because the model was
    # unavailable or returned nothing usable.
    is_fallback: bool = False


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="family_loop",
        model=model_name(),
        description=(
            "Drafts a short text message asking a family member for help with "
            "a specific point on a form. Text only, never an image."
        ),
        instruction=INSTRUCTION,
    )


_agent: Optional[LlmAgent] = None


def _get_agent() -> LlmAgent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def _subject(form: str) -> str:
    """"Help with <form>", trimmed at a word boundary rather than mid-word."""
    subject = f"Help with {form}"
    if len(subject) <= 60:
        return subject
    return subject[:60].rsplit(" ", 1)[0].rstrip(" ,(") + "…"


def _fallback(form_guess: str, stuck_on: str, reason: str) -> FamilySummary:
    """Template used when the model is unavailable.

    Worth having: the family loop is offered at the moment the user is most
    stuck, which is the worst moment to show them an error.
    """
    form = form_guess or "an official form"
    message = (
        f"I'm filling in {form} and I've got as far as "
        f"{stuck_on or 'the declaration at the end'}. "
        f"{reason} "
        "Can you take a look with me before I sign anything?"
    )
    return FamilySummary(
        message=" ".join(message.split()),
        subject=_subject(form),
        is_fallback=True,
    )


async def summarise(
    *,
    form_guess: str,
    completed_labels: List[str],
    stuck_on: str,
    reason: str,
    language: str = config.DEFAULT_LANGUAGE,
) -> FamilySummary:
    """Draft the message. Text in, text out - an image cannot be passed here.

    Never raises: falls back to a template so the handoff always works.
    """
    if config.USE_STUB:
        return _fallback(form_guess, stuck_on, reason)

    language_name = config.SUPPORTED_LANGUAGES.get(
        language, config.SUPPORTED_LANGUAGES["en"]
    )
    done = ", ".join(completed_labels) if completed_labels else "nothing yet"
    prompt = (
        f"FORM: {form_guess or 'an official form'}\n"
        f"FIELDS ALREADY FILLED: {done}\n"
        f"STUCK ON: {stuck_on or 'the final declaration'}\n"
        f"WHY WE STOPPED: {reason}\n"
        f"WRITE IN: {language_name}\n"
    )

    try:
        raw = await run_agent(_get_agent(), prompt)
    except Exception:
        logger.exception("family_loop model call failed; using template")
        return _fallback(form_guess, stuck_on, reason)

    payload = parse_json(raw, where="family_loop")
    message = str(payload.get("message", "")).strip()
    if not message:
        return _fallback(form_guess, stuck_on, reason)

    try:
        # Final check on the one artifact that leaves toward another person.
        message = assert_clean(message)
        subject = assert_clean(str(payload.get("subject", "")).strip())
    except ValueError:
        logger.error("family_loop output failed the PII check; using template")
        return _fallback(form_guess, stuck_on, reason)

    return FamilySummary(message=message, subject=subject or "Help with a form")
