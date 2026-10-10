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
    # Stable identity, assigned by position on the form. Labels are NOT
    # unique: the real CHAS form carries "Name (in BLOCK LETTERS, as in
    # NRIC)" and "Mobile Number" twice, once in Section 1A for the applicant
    # and again in Section 1B for a family member. Keying off the label
    # would tick both when the user finishes one.
    key: str = ""
    label: str = ""
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

    def key_for_label(self, label: str) -> Optional[str]:
        """First field with this label. Used only to resolve the model's
        `focus_label`, which names a field rather than keying one."""
        for f in self.fields:
            if f.label == label:
                return f.key
        return None


def assign_keys(fields: List[DetectedField]) -> List[DetectedField]:
    """Key fields by position, so duplicate labels stay distinct."""
    for i, f in enumerate(fields):
        f.key = f"f{i:02d}"
    return fields


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
        fields=assign_keys(fields),
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
    """Offline stand-in, matching the real Dec 2025 CHAS form.

    Labels and options are copied from the published PDF, not invented. If
    the stub drifts from the corpus, stub-mode demos start explaining fields
    that are not on the form.
    """
    return VisionResult(
        form_guess="Application for CHAS Subsidies (Dec 2025)",
        language="English",
        fields=assign_keys([
            DetectedField(
                label="Name (in BLOCK LETTERS, as in NRIC)",
                kind="text",
                notes="Section 1A. Main applicant.",
            ),
            DetectedField(
                label="Pink NRIC / Birth Certificate Number",
                kind="text",
                notes="Section 1A. Boxed: one letter, seven digits, one letter. "
                      "Main applicant must be a Singapore Citizen.",
            ),
            DetectedField(
                label="Mobile Number",
                kind="number",
                notes="Section 1A. Either this or a home phone number is required.",
            ),
            DetectedField(
                label="Dwelling Type",
                kind="choice",
                options=[
                    "HDB Flat",
                    "Private Housing (Including Executive Condo)",
                    "Institution (MOH/MSF licensed home)",
                    "Others (please specify)",
                ],
                notes="Section 1A. Tick one. Based on the NRIC address.",
            ),
            DetectedField(
                label="Rental Status of Residence",
                kind="choice",
                options=[
                    "Renting from Government",
                    "Renting from Open Market",
                    "Not Rented (e.g. bought or owned)",
                ],
                notes="Section 1A. Tick one.",
            ),
            DetectedField(
                label="Particulars of Family Members Sharing the Same NRIC Address",
                kind="text",
                notes="Section 1B. Per person: name, identification number with "
                      "Pink NRIC / Blue NRIC / Birth Certificate Number / FIN "
                      "circled, relationship, optional mobile.",
            ),
            DetectedField(
                label="Consent and Declaration by Main Applicant (Section 2B)",
                kind="signature",
                notes="Consents to the Government, IRAS and CPF Board disclosing "
                      "income and CPF information; declares all information true "
                      "and accurate.",
            ),
            DetectedField(
                label="Signature / Thumbprint of Main Applicant (Section 3)",
                kind="signature",
                notes="Signature or thumbprint, with date. Form is returned "
                      "unprocessed without it.",
            ),
        ]),
        focus_label="Rental Status of Residence",
        confidence=0.91,
    )
