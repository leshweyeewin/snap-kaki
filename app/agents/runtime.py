"""Thin wrapper for running one ADK agent and getting its answer back.

Every sub-agent here is a one-shot reasoner: it receives everything it needs
in the prompt and returns one response. Conversation state lives in Firestore
(see app/session.py), not in ADK's session service.

That split is deliberate. The orchestrator must be able to replay or skip a
sub-agent without a hidden chat history changing the answer, and a stateless
sub-agent is one we can unit-test with a fixed input.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app import config
from app.redaction import assert_clean

logger = logging.getLogger(__name__)

APP_NAME = "snapkaki"

# One session service for the process. Sessions created here are ephemeral
# scratch space for a single agent call, not user state.
_session_service = InMemorySessionService()
_runners: dict[str, Runner] = {}


def _runner_for(agent: LlmAgent) -> Runner:
    runner = _runners.get(agent.name)
    if runner is None:
        runner = Runner(
            app_name=APP_NAME,
            agent=agent,
            session_service=_session_service,
            auto_create_session=True,
        )
        _runners[agent.name] = runner
    return runner


async def run_agent(
    agent: LlmAgent,
    prompt: str,
    *,
    image: Optional[bytes] = None,
    image_mime: str = "image/jpeg",
    redact_prompt: bool = True,
) -> str:
    """Run `agent` on `prompt` and return its final response text.

    `redact_prompt` is on by default and should only be turned off for text
    we authored ourselves. Turning it off for anything derived from user
    input defeats the PII boundary.
    """
    if redact_prompt:
        prompt = assert_clean(prompt)

    parts: list[types.Part] = [types.Part.from_text(text=prompt)]
    if image is not None:
        # The image itself is never redactable, which is exactly why the
        # vision agent is instructed to report field STRUCTURE and never
        # transcribe a value. See app/agents/vision.py.
        parts.append(types.Part.from_bytes(data=image, mime_type=image_mime))

    runner = _runner_for(agent)
    session_id = f"{agent.name}-{uuid.uuid4().hex}"

    chunks: list[str] = []
    async for event in runner.run_async(
        user_id="snapkaki-agent",
        session_id=session_id,
        new_message=types.Content(role="user", parts=parts),
    ):
        if event.error_message:
            logger.error("agent %s error: %s", agent.name, event.error_message)
        if not event.is_final_response() or not event.content:
            continue
        for part in event.content.parts or []:
            if part.text:
                chunks.append(part.text)

    return "".join(chunks).strip()


def parse_json(raw: str, *, where: str) -> dict[str, Any]:
    """Parse a model's JSON response, tolerating a ```json fence.

    Returns {} on failure rather than raising. Every caller has a defined
    behaviour for "the model gave me nothing usable" — it drives confidence
    to zero, which trips the gate. A parse failure must never read as a
    confident answer.
    """
    if not raw:
        return {}
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("%s: could not parse JSON from %r", where, text[:200])
        return {}
    return value if isinstance(value, dict) else {}


def clamp_confidence(value: Any) -> float:
    """Coerce a model-reported confidence into [0, 1]. Junk becomes 0.0."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def model_name() -> str:
    return config.GEMINI_MODEL
