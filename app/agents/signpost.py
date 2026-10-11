"""Signpost agent: when we have no corpus for a form, find who does.

This is the one place SnapKaki touches the open web, and the boundary is
narrow on purpose.

It does NOT answer "what does this field mean". That was the first instinct
and it is wrong: the reason we grounded the explainer on a hand-checked
corpus is that a model answering from unchecked sources is confidently wrong
about form revisions. Google Search has exactly that failure mode, worse —
it surfaces visa-agency content farms that read as authoritative. On a visa
application, a confident wrong answer is the most expensive thing we could
produce.

So search is used to LOCATE, never to INTERPRET. It answers one factual
question: which official body issues this form, and where is their page.
The user is then handed to that body. The product still refuses to explain
the form, and says so.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from app import config
from app.agents.runtime import model_name, parse_json, run_agent

logger = logging.getLogger(__name__)

INSTRUCTION = """\
You are the signpost component of SnapKaki. Someone has photographed an
official form that we hold no checked guidance for. Your single job is to
identify WHO is responsible for that form, so they can be sent to the right
place.

You have Google Search. Use it to confirm the issuing body and find their
official page.

HARD LIMITS, and they matter more than being helpful:

1. Do NOT explain any field on the form. Do not say what a question means,
   what to write, what the person qualifies for, or what any term means.
   That is not your job and getting it wrong is expensive.
2. Do NOT summarise requirements, eligibility, fees or processing times,
   even if a search result states them plainly. Those change, and a stale
   figure delivered confidently is worse than no figure.
3. Only cite an OFFICIAL source: the issuing government body, agency or
   embassy. Never a blog, a visa agency, a forum, a law firm, or any site
   selling a related service. If you cannot find an official page, say so
   and return null for the url.
4. If you are not confident which body issues this form, say that instead
   of guessing.

Return ONLY a JSON object, no prose and no code fence:

{
  "authority": "the official body responsible, in plain words, or null",
  "url": "their official page for this form, or null",
  "contact": "an official phone number or contact route if one is clearly
              stated on an official page, else null",
  "confidence": 0.0 to 1.0
}
"""


@dataclass
class Signpost:
    authority: Optional[str] = None
    url: Optional[str] = None
    contact: Optional[str] = None
    confidence: float = 0.0

    @property
    def useful(self) -> bool:
        return bool(self.authority) and self.confidence >= 0.5


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="signpost",
        model=model_name(),
        description=(
            "Finds the official body responsible for an unrecognised form. "
            "Locates; never interprets."
        ),
        instruction=INSTRUCTION,
        tools=[google_search],
    )


_agent: Optional[LlmAgent] = None


def _get_agent() -> LlmAgent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


# Anything outside this set is not an official source. Deliberately a
# allowlist of suffixes rather than a blocklist: the failure we are guarding
# against is a plausible-looking commercial page, and there are infinitely
# many of those.
OFFICIAL_SUFFIXES = (
    ".gov", ".gov.sg", ".gov.uk", ".gov.au", ".govt.nz",
    ".go.jp", ".go.kr", ".gov.in", ".gob.es",
    ".admin.ch", ".europa.eu", ".int",
    ".edu", ".edu.sg",
)


def _looks_official(url: str) -> bool:
    if not url:
        return False
    low = url.lower()
    if not low.startswith(("http://", "https://")):
        return False
    host = low.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    # Strip a trailing dot and any port already removed above.
    host = host.rstrip(".")
    return any(host == s.lstrip(".") or host.endswith(s) for s in OFFICIAL_SUFFIXES)


async def find(form_guess: str) -> Signpost:
    """Locate the authority behind an unrecognised form. Never raises."""
    if config.USE_STUB:
        return Signpost(
            authority="[stub] the agency that issued this form",
            url=None,
            contact=None,
            confidence=0.6,
        )

    prompt = (
        f"FORM, as read from a photograph: {form_guess or '(unclear)'}\n\n"
        "Identify the official body responsible for this form and their "
        "official page. Do not explain the form."
    )

    try:
        raw = await run_agent(_get_agent(), prompt, redact_prompt=False)
    except Exception:
        logger.exception("signpost search failed")
        return Signpost()

    payload = parse_json(raw, where="signpost")
    if not payload:
        return Signpost()

    url = payload.get("url") or None
    if url and not _looks_official(str(url)):
        # A plausible commercial page is exactly what this guard exists for.
        logger.warning("signpost returned a non-official url; dropping it")
        url = None

    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0

    authority = payload.get("authority")
    contact = payload.get("contact")
    return Signpost(
        authority=str(authority).strip() if authority else None,
        url=str(url).strip() if url else None,
        contact=str(contact).strip() if contact else None,
        confidence=confidence,
    )
