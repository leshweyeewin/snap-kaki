"""Session state, in Firestore with an in-memory fallback.

What is stored is the point of this module. A session holds:

  - the form's field STRUCTURE (labels, kinds, printed options)
  - which field labels the user has told us they finished
  - the language they picked, and a short event trail

What is never stored, and has nowhere to go:

  - any value the user entered

There is no `value` anywhere in this schema. The user types their
identification number into the paper form or the government website, not
into SnapKaki, so we have nothing to keep. "SnapKaki never sees your
details" is enforced by there being no field to put them in.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app import config
from app.agents.vision import DetectedField

logger = logging.getLogger(__name__)


@dataclass
class FormSession:
    session_id: str
    form_id: str = config.DEMO_FORM_ID
    form_guess: str = ""
    language: str = config.DEFAULT_LANGUAGE
    fields: List[DetectedField] = field(default_factory=list)
    completed: List[str] = field(default_factory=list)
    history: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def completed_set(self) -> set[str]:
        """Completed field KEYS, not labels. See DetectedField.key."""
        return set(self.completed)

    def mark_complete(self, key: str) -> None:
        """Record that a field is done. The key only - never the value."""
        if key and key not in self.completed:
            self.completed.append(key)

    def note(self, event: str) -> None:
        """Append to the event trail, keeping only what guidance needs."""
        if event:
            self.history.append(event)
            del self.history[:-10]

    def field_by_key(self, key: str) -> Optional[DetectedField]:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    def label_for(self, key: str) -> str:
        found = self.field_by_key(key)
        return found.label if found else key

    def completed_labels(self) -> List[str]:
        """Display labels for the finished fields, in form order."""
        done = self.completed_set
        return [f.label for f in self.fields if f.key in done]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "form_id": self.form_id,
            "form_guess": self.form_guess,
            "language": self.language,
            "fields": [asdict(f) for f in self.fields],
            "completed": list(self.completed),
            "history": list(self.history),
            "created_at": self.created_at,
            "updated_at": time.time(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormSession":
        fields = [
            DetectedField(
                key=d.get("key", f"f{i:02d}"),
                label=d.get("label", ""),
                kind=d.get("kind", "unknown"),
                options=list(d.get("options") or []),
                has_value=bool(d.get("has_value", False)),
                notes=d.get("notes", ""),
            )
            for i, d in enumerate(data.get("fields") or [])
        ]
        return cls(
            session_id=data["session_id"],
            form_id=data.get("form_id", config.DEMO_FORM_ID),
            form_guess=data.get("form_guess", ""),
            language=data.get("language", config.DEFAULT_LANGUAGE),
            fields=fields,
            completed=list(data.get("completed") or []),
            history=list(data.get("history") or []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


class SessionStore:
    """Firestore-backed, with an in-memory dict as the fallback.

    The fallback matters for the demo: a Firestore hiccup should cost us
    persistence across instances, not the ability to run a session at all.
    """

    def __init__(self) -> None:
        self._memory: Dict[str, FormSession] = {}
        self._client = None
        self._firestore_ok = not config.USE_STUB

    def _collection(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=config.PROJECT_ID)
        return self._client.collection(config.SESSION_COLLECTION)

    def create(self, *, language: str = config.DEFAULT_LANGUAGE) -> FormSession:
        session = FormSession(
            session_id=uuid.uuid4().hex[:12],
            language=language if language in config.SUPPORTED_LANGUAGES
            else config.DEFAULT_LANGUAGE,
        )
        self.save(session)
        return session

    def get(self, session_id: str) -> Optional[FormSession]:
        if session_id in self._memory:
            return self._memory[session_id]

        if not self._firestore_ok:
            return None
        try:
            doc = self._collection().document(session_id).get()
        except Exception:
            logger.exception("Firestore read failed; serving from memory only")
            self._firestore_ok = False
            return None
        if not doc.exists:
            return None
        session = FormSession.from_dict(doc.to_dict())
        self._memory[session_id] = session
        return session

    def save(self, session: FormSession) -> None:
        session.updated_at = time.time()
        self._memory[session.session_id] = session

        if not self._firestore_ok:
            return
        try:
            self._collection().document(session.session_id).set(session.to_dict())
        except Exception:
            logger.exception("Firestore write failed; continuing in memory")
            self._firestore_ok = False


store = SessionStore()
