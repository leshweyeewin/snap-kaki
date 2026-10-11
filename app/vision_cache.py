"""Cache a reading of a form page, keyed by the bytes of the photograph.

Reading a dense page costs about eight seconds and a billed model call.
Photograph the same page twice - which happens constantly: re-framing a bad
shot, coming back to a form, or re-taking a shot while filming - and
without this we pay both again for an answer we already have.

What is stored is the same thing the session stores: field labels, kinds and
printed options. No image, and no value the user wrote. The key is a hash of
the image, which is one-way, so nothing about the photograph is recoverable
from the cache.

A note on sharing: two people photographing the same blank government form
produce the same hash and share an entry. That is correct - the structure of
a public form is not anybody's private data. A form with handwriting on it
hashes differently anyway, and we would still only keep its structure.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict
from typing import Optional

from app import config
from app.agents.vision import DetectedField, VisionResult

logger = logging.getLogger(__name__)

COLLECTION = "vision_cache"

# Re-read a page after a week. The form itself can be revised, and a stale
# reading is worse than a slow one.
TTL_SECONDS = 7 * 24 * 60 * 60

_client = None
_available = not config.USE_STUB


def key_for(image: bytes, form_id: str) -> str:
    """Content hash of the photograph, namespaced by corpus version."""
    return f"{form_id}-{hashlib.sha256(image).hexdigest()[:32]}"


def _collection():
    global _client
    if _client is None:
        from google.cloud import firestore

        _client = firestore.Client(project=config.PROJECT_ID)
    return _client.collection(COLLECTION)


def get(image: bytes, form_id: str) -> Optional[VisionResult]:
    """A previous reading of this exact image, or None. Never raises."""
    global _available
    if not _available:
        return None
    try:
        doc = _collection().document(key_for(image, form_id)).get()
    except Exception:
        logger.exception("vision cache read failed; continuing without it")
        _available = False
        return None

    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    if time.time() - data.get("cached_at", 0) > TTL_SECONDS:
        return None

    return VisionResult(
        form_guess=data.get("form_guess", ""),
        language=data.get("language", ""),
        fields=[
            DetectedField(
                key=f.get("key", ""),
                label=f.get("label", ""),
                kind=f.get("kind", "unknown"),
                options=list(f.get("options") or []),
                has_value=bool(f.get("has_value", False)),
                notes=f.get("notes", ""),
            )
            for f in (data.get("fields") or [])
        ],
        focus_label=data.get("focus_label"),
        confidence=float(data.get("confidence", 0.0)),
    )


def put(image: bytes, form_id: str, reading: VisionResult) -> None:
    """Store a reading. Never raises; a cache miss is not an error."""
    global _available
    if not _available or reading.is_empty:
        return
    # A reading we did not trust is not worth keeping.
    if reading.leaked_pii or reading.confidence < config.CONFIDENCE_FLOOR:
        return
    try:
        _collection().document(key_for(image, form_id)).set(
            {
                "form_guess": reading.form_guess,
                "language": reading.language,
                "fields": [asdict(f) for f in reading.fields],
                "focus_label": reading.focus_label,
                "confidence": reading.confidence,
                "cached_at": time.time(),
            }
        )
    except Exception:
        logger.exception("vision cache write failed; continuing without it")
        _available = False
