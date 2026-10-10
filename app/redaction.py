"""PII boundary. Nothing leaves the device layer for Gemini until it has
passed through here. Raw values are replaced by typed placeholders so the
model reasons over the form's STRUCTURE, never the user's actual data.

This is deliberately conservative: it is a backstop. The primary defense is
that the user types sensitive values directly into the form themselves, so
those digits are never captured at all. Redaction catches anything that
slips into text we do send up (field labels, pre-filled values, OCR text).
"""
import re
from dataclasses import dataclass, field
from typing import Dict

# Singapore-centric patterns. Order matters: most specific first.
_PATTERNS = [
    ("NRIC", re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.I)),
    ("PHONE", re.compile(r"\b(?:\+65[\s-]?)?[689]\d{3}[\s-]?\d{4}\b")),
    ("POSTAL", re.compile(r"\b\d{6}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("DOB", re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")),
]


@dataclass
class RedactionResult:
    masked_text: str
    # placeholder -> count, so the caller knows what kind of data is present
    # without ever seeing the values.
    found: Dict[str, int] = field(default_factory=dict)

    @property
    def has_pii(self) -> bool:
        return bool(self.found)


def redact(text: str) -> RedactionResult:
    """Replace every detected PII span with a typed placeholder like [NRIC]."""
    if not text:
        return RedactionResult(masked_text=text or "")
    found: Dict[str, int] = {}
    masked = text
    for label, pattern in _PATTERNS:
        def _sub(_m, _label=label):
            found[_label] = found.get(_label, 0) + 1
            return f"[{_label}]"
        masked = pattern.sub(_sub, masked)
    return RedactionResult(masked_text=masked, found=found)


def assert_clean(text: str) -> str:
    """Last line of defense before an outbound model call. Returns masked
    text; raises if somehow a known pattern remains after masking."""
    result = redact(text)
    # Re-scan the masked output; if anything matches, we refuse to send.
    for _label, pattern in _PATTERNS:
        if pattern.search(result.masked_text):
            raise ValueError("PII detected after redaction; refusing to send upstream")
    return result.masked_text
