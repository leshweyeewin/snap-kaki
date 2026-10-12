"""Field-explainer sub-agent: "what is this field asking me?"

Grounded on the Firestore guidance corpus. The agent is given retrieved
chunks and told they are the only thing it may explain from. If the answer
is not in there, it must say so.

That refusal is the feature. SnapKaki's broader pitch covers forms where a
confident wrong answer is expensive — a visa form, a tenancy agreement. The
product is only safe at that breadth if "I don't have guidance on this" is
a first-class response rather than a failure mode.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from google.adk.agents import LlmAgent

from app import config
from app.agents.runtime import clamp_confidence, model_name, parse_json, run_agent
from app.rag import retriever

logger = logging.getLogger(__name__)

INSTRUCTION = """\
You are the field-explainer in SnapKaki. Someone is part-way through an
official form and does not understand one of the fields. You explain it.

You will be given:
  - the field label, as printed on the form
  - the person's question, if they asked one
  - GUIDANCE: retrieved passages about this form
  - the language to answer in

Rules, in order of importance:

1. Explain ONLY from GUIDANCE. It is the sole source you may draw on. Do not
   add facts from your own knowledge of government schemes, even if you are
   confident they are correct — this corpus is what has been checked.
2. If GUIDANCE does not answer the question, say plainly that you do not have
   guidance on it and that this is one to ask the agency or a family member
   about. Then set "confidence" low. Never improvise to seem useful.
3. Never tell the person what to put. You explain what the field is ASKING
   and how to work out their own answer - "look at the colour of the card in
   your hand" - not "write Pink NRIC". The value is always theirs to enter.
4. Answer in the requested language. If it is a spoken dialect such as
   Hokkien, write it romanised the way a person would actually say it.
5. BUT keep anything PRINTED ON THE FORM in the exact words the form uses,
   even mid-sentence in another language. Option names, field labels,
   section numbers: reproduce them verbatim and put your translation in
   brackets after.

   Right:  "...pilih 'Not Rented (e.g. bought or owned)' (tidak disewa)"
   Wrong:  "...pilih 'Tidak Disewa'"

   The second one is unfindable. They are holding a sheet of paper printed
   in English and scanning it for the words you just said. A translated
   option name is not on it.
6. Short sentences. No jargon. Assume no familiarity with government forms.
   Assume intelligence - the person is confused by the form, not slow.

Return ONLY a JSON object, no prose and no code fence:

{
  "explanation": "your explanation, 2-5 short sentences",
  "how_to_decide": "the concrete thing they can look at or check to find
                    their own answer, or null if GUIDANCE does not say",
  "grounded": true if your answer came from GUIDANCE, false if you could not
              find it there,
  "ask_someone": true if this field genuinely needs the agency or a family
                 member rather than an explanation,
  "confidence": 0.0 to 1.0
}
"""


@dataclass
class Explanation:
    explanation: str = ""
    how_to_decide: Optional[str] = None
    grounded: bool = False
    ask_someone: bool = False
    confidence: float = 0.0
    sources: List[str] = None  # headings used, for the "why it said that" trail

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="field_explainer",
        model=model_name(),
        description=(
            "Explains what one form field is asking, strictly from retrieved "
            "guidance, in the user's language."
        ),
        instruction=INSTRUCTION,
    )


_agent: Optional[LlmAgent] = None


def _get_agent() -> LlmAgent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


# Asked for by the user, not inferred. Deliberately about sentence shape and
# vocabulary rather than tone: "simpler" must not become patronising, and the
# person asking for it is confused by a form, not slow.
SIMPLE_MODE = """
PLAIN LANGUAGE: this person has asked for the simplest version.

- Short sentences, one idea each. Under 12 words where you can.
- The most CONCRETE everyday words available. Never reach for an abstract
  phrase when a plain one exists: write "do you rent or own?", never "how
  you occupy your home". Abstraction is the opposite of simple, and it is
  the usual way a rewrite gets worse instead of better.
- Name the thing they can look at or hold: the card, the letter, the lease.
- No scheme names, no abbreviations, no officialese.
- Shorten the SENTENCES, not the answer. Leaving out what they need is not
  simplifying.
- Do not talk down to them. They are confused by a form, not slow.
"""


def _build_prompt(
    field_label: str,
    question: str,
    context: str,
    language: str,
    simple: bool = False,
) -> str:
    language_name = config.SUPPORTED_LANGUAGES.get(language, config.SUPPORTED_LANGUAGES["en"])
    return (
        f"FIELD LABEL: {field_label}\n"
        f"QUESTION: {question or '(they did not ask anything specific)'}\n"
        f"ANSWER IN: {language_name}\n"
        f"{SIMPLE_MODE if simple else ''}\n"
        f"GUIDANCE:\n{context}\n"
    )


async def explain(
    field_label: str,
    *,
    question: str = "",
    language: str = config.DEFAULT_LANGUAGE,
    form_id: str = config.DEMO_FORM_ID,
    simple: bool = False,
) -> Explanation:
    """Explain one field. Never raises; a failure comes back as low confidence."""
    retrieval_query = f"{field_label} {question}".strip()
    chunks = retriever.retrieve(retrieval_query, k=3, form_id=form_id)
    sources = [c.heading for c in chunks]

    if not chunks:
        # Nothing retrieved means nothing we are allowed to speak from.
        # Short-circuit rather than let the model answer unguided.
        return Explanation(
            explanation=(
                "I don't have checked guidance on this field, so I'm not going "
                "to guess at it. This is one to ask about."
            ),
            grounded=False,
            ask_someone=True,
            confidence=0.0,
            sources=sources,
        )

    if config.USE_STUB:
        return _stub_explanation(field_label, chunks, sources)

    prompt = _build_prompt(
        field_label, question, retriever.as_context_block(chunks), language, simple
    )
    raw = await run_agent(_get_agent(), prompt)
    payload = parse_json(raw, where="field_explainer")

    if not payload:
        return Explanation(
            explanation="Something went wrong reading that field. Let's try again.",
            grounded=False,
            confidence=0.0,
            sources=sources,
        )

    grounded = bool(payload.get("grounded", False))
    confidence = clamp_confidence(payload.get("confidence"))
    if not grounded:
        # An ungrounded answer is never allowed to look confident, whatever
        # the model reported.
        confidence = min(confidence, 0.2)

    how = payload.get("how_to_decide")
    return Explanation(
        explanation=str(payload.get("explanation", "")).strip(),
        how_to_decide=str(how).strip() if how else None,
        grounded=grounded,
        ask_someone=bool(payload.get("ask_someone", False)),
        confidence=confidence,
        sources=sources,
    )


def _stub_explanation(field_label: str, chunks, sources) -> Explanation:
    """Offline stand-in: echo the retrieved passage so the shape is real."""
    first = chunks[0]
    body = " ".join(first.text.split())
    return Explanation(
        explanation=f"[stub] {first.heading}: {body[:280]}",
        how_to_decide="[stub] Check the document or card in front of you.",
        grounded=True,
        ask_someone="STOP HERE" in first.heading,
        confidence=0.88,
        sources=sources,
    )
