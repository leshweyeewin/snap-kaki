"""Is this the form we actually hold guidance for?

The explainer already refuses questions the corpus does not cover — verified
against real visa-form questions, which come back grounded=False at
confidence 0.0-0.1. But that is an emergent property of the prompt, and it
only protects the ASK path. Guidance would still happily propose "enter your
name" on a form it knows nothing about.

So the check is made explicit and made early, on the scan. Deciding it here
rather than inside an agent keeps it testable with no network and means the
answer cannot vary between runs.

Deliberately pure: no model call, no retrieval. A form the user photographed
is either recognisable from its own words or it is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List

from app import config


@dataclass
class FormMatch:
    known: bool
    score: int
    matched: List[str]

    @property
    def unknown(self) -> bool:
        return not self.known


@lru_cache(maxsize=1)
def _patterns() -> tuple[tuple[str, "re.Pattern[str]"], ...]:
    """Whole-word patterns, one per marker.

    A bare substring test is wrong here: "fin" matches inside "confirm" and
    "define", both of which appear on ordinary forms, and a false match
    makes an unrelated document look like ours - the failure that would
    silently re-enable guessing.
    """
    return tuple(
        (m, re.compile(rf"\b{re.escape(m)}\b", re.I)) for m in config.FORM_MARKERS
    )


def _markers_in(text: str) -> set[str]:
    if not text:
        return set()
    return {m for m, pattern in _patterns() if pattern.search(text)}


def match(form_guess: str, field_labels: Iterable[str]) -> FormMatch:
    """Score a reading against the corpus we hold.

    A marker in the form's own name counts double: the model naming "CHAS"
    is stronger evidence than a field label mentioning an NRIC, which plenty
    of Singapore forms do.
    """
    in_name = _markers_in(form_guess)
    in_fields: set[str] = set()
    for label in field_labels:
        in_fields |= _markers_in(label)

    score = 2 * len(in_name) + len(in_fields - in_name)
    matched = sorted(in_name | in_fields)
    return FormMatch(
        known=score >= config.FORM_MATCH_THRESHOLD,
        score=score,
        matched=matched,
    )
