"""Vision sub-agent: a photo or screenshot of a form -> its structure as JSON.

The one rule that matters here: this agent reports what the form ASKS, never
what the user has WRITTEN. For every field it returns a label, a kind, and a
boolean `has_value` — never the value itself.

That is the PII boundary at the camera. An image cannot be redacted before
it reaches the model, so the defense has to be in what we ask the model to
emit and in checking what comes back. `extract_fields` re-scans the output
and drops any field whose notes leaked something that looks like real data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from google.adk.agents import LlmAgent

from app import config
from app.agents.runtime import clamp_confidence, model_name, parse_json, run_agent
from app.redaction import redact

logger = logging.getLogger(__name__)

FIELD_KINDS = {"text", "number", "date", "choice", "checkbox", "signature", "unknown"}

INSTRUCTION = """\
You are the vision component of SnapKaki, a helper for people filling in
official forms. You are shown a photo or screenshot of a form.

Your job is to describe the STRUCTURE of the form: what it asks for.

ABSOLUTE RULE — never transcribe a value the user has written or typed.
Do not output names, identification numbers, phone numbers, addresses,
postal codes, dates of birth, or any handwritten or filled-in content. If a
field already has something in it, say so with "has_value": true and move
on. Reporting the value is a privacy breach, not helpfulness.

Return ONLY a JSON object, no prose and no code fence:

{
  "form_guess": "best guess at which form this is, in plain words",
  "language": "the language the form is printed in",
  "fields": [
    {
      "label": "the printed question or field name, copied as printed",
      "kind": "text | number | date | choice | checkbox | signature | unknown",
      "options": ["the printed choices, if this is a choice field"],
      "has_value": true or false,
      "notes": "anything about how the field is laid out that a confused
                person would need - e.g. 'circle one of four', 'tick box'.
                Never put user data here."
    }
  ],
  "focus_label": "the label of the field the camera is pointed at, or null",
  "confidence": 0.0 to 1.0 - how sure you are you read this form correctly
}

Be honest in "confidence". A blurry photo, a cropped page, or a form you do
not recognise should score low. A low score makes SnapKaki stop and ask for
a better photo, which is the correct outcome. Overstating confidence sends a
confused person down a wrong path.
"""


@dataclass
class DetectedField:
    label: str
    kind: str = "unknown"
    options: List[str] = field(default_factory=list)
    has_value: bool = False
    notes: str = ""


@dataclass
class VisionResult:
    form_guess: str = ""
    language: str = ""
    fields: List[DetectedField] = field(default_factory=list)
    focus_label: Optional[str] = None
    confidence: float = 0.0
    leaked_pii: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.fields


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="vision",
        model=model_name(),
        description=(
            "Reads a photo or screenshot of a form and reports the fields it "
            "asks for, never the values filled in."
        ),
        instruction=INSTRUCTION,
    )


_agent: Optional[LlmAgent] = None


def _get_agent() -> LlmAgent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def _sanitise(text: str) -> tuple[str, bool]:
    """Mask anything that looks like user data. Returns (text, leaked)."""
    result = redact(text or "")
    return result.masked_text, result.has_pii


def _parse(payload: dict) -> VisionResult:
    leaked = False
    fields: List[DetectedField] = []

    for raw in payload.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        label, label_leaked = _sanitise(str(raw.get("label", "")).strip())
        notes, notes_leaked = _sanitise(str(raw.get("notes", "")).strip())
        leaked = leaked or label_leaked or notes_leaked
        if not label:
            continue

        kind = str(raw.get("kind", "unknown")).strip().lower()
        if kind not in FIELD_KINDS:
            kind = "unknown"

        options = []
        for opt in raw.get("options") or []:
            masked, opt_leaked = _sanitise(str(opt).strip())
            leaked = leaked or opt_leaked
            if masked:
                options.append(masked)

        fields.append(
            DetectedField(
                label=label,
                kind=kind,
                options=options,
                has_value=bool(raw.get("has_value", False)),
                notes=notes,
            )
        )

    focus = payload.get("focus_label")
    focus_label = None
    if focus:
        focus_label, focus_leaked = _sanitise(str(focus).strip())
        leaked = leaked or focus_leaked

    confidence = clamp_confidence(payload.get("confidence"))
    if leaked:
        # The model was told not to transcribe values and did anyway. We
        # masked it, but we no longer trust its judgement on this image.
        logger.warning("vision agent emitted PII-shaped text; confidence floored")
        confidence = 0.0

    return VisionResult(
        form_guess=str(payload.get("form_guess", "")).strip(),
        language=str(payload.get("language", "")).strip(),
        fields=fields,
        focus_label=focus_label,
        confidence=confidence,
        leaked_pii=leaked,
    )


async def extract_fields(image: bytes, *, image_mime: str = "image/jpeg") -> VisionResult:
    """Read a form image into structure. Never raises on a bad model reply."""
    if config.USE_STUB:
        return _stub_result()

    raw = await run_agent(
        _get_agent(),
        "Read this form and return its structure as JSON.",
        image=image,
        image_mime=image_mime,
        redact_prompt=False,  # our own prompt text, no user data in it
    )
    payload = parse_json(raw, where="vision")
    if not payload:
        return VisionResult(confidence=0.0)
    return _parse(payload)


def _stub_result() -> VisionResult:
    """Offline stand-in: the real CHAS fields, so the demo runs with no network."""
    return VisionResult(
        form_guess="CHAS (Community Health Assist Scheme) application form",
        language="English",
        fields=[
            DetectedField(
                label="Identification Type",
                kind="choice",
                options=["Pink NRIC", "Blue NRIC", "Birth Certificate", "FIN"],
                notes="Circle one of four printed options.",
            ),
            DetectedField(
                label="Pink NRIC / Birth Certificate Number",
                kind="text",
                notes="One letter, seven digits, one letter.",
            ),
            DetectedField(
                label="Dwelling Type",
                kind="choice",
                options=[
                    "1-room / 2-room HDB",
                    "3-room HDB",
                    "4-room HDB",
                    "5-room / Executive HDB",
                    "Private housing",
                    "Landed property",
                ],
                notes="Tick one.",
            ),
            DetectedField(
                label="Rental Status",
                kind="choice",
                options=["Owned", "Rented from HDB", "Rented from open market"],
                notes="Tick one.",
            ),
            DetectedField(
                label="Mobile Number",
                kind="number",
                notes="Eight digits, starting with 8 or 9.",
            ),
            DetectedField(
                label="Family members living at the same address",
                kind="text",
                notes="Table: name, identification number, relationship.",
            ),
            DetectedField(
                label="Declaration and Consent (Clause 11)",
                kind="signature",
                notes="Signature or thumbprint. Declares information true and "
                      "consents to IRAS/CPF income disclosure.",
            ),
        ],
        focus_label="Rental Status",
        confidence=0.91,
    )
