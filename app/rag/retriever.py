"""Retrieval over the form-guidance corpus.

Two paths, same interface:

- Firestore vector search, used in the deployed app.
- A local keyword fallback over the same markdown chunks, used in stub mode
  and whenever Firestore is unreachable.

The fallback is not a nicety. The explainer is only allowed to speak from
retrieved text, so if retrieval dies the whole product goes mute. A demo
that loses its network should degrade to "slightly worse explanations",
not to a blank screen.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app import config

logger = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).parent / "corpus"
# Firestore caps the stored vector dimension; 768 is text-embedding-004's native size.
EMBED_DIM = 768


@dataclass
class Chunk:
    """One retrievable passage of form guidance."""

    chunk_id: str
    form_id: str
    heading: str
    text: str

    def as_context(self) -> str:
        return f"### {self.heading}\n{self.text}"


def load_corpus_chunks(form_id: str = config.DEMO_FORM_ID) -> List[Chunk]:
    """Split every corpus markdown file on `##` headings.

    One heading == one chunk. The corpus is authored with that in mind, so
    chunking stays dumb and predictable rather than sliding-window clever.
    """
    chunks: List[Chunk] = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        # Drop the H1 preamble; it is editorial notes for us, not guidance.
        sections = re.split(r"^##\s+", raw, flags=re.MULTILINE)[1:]
        for i, section in enumerate(sections):
            heading, _, body = section.partition("\n")
            body = body.strip()
            if not body:
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{path.stem}-{i:02d}",
                    form_id=form_id,
                    heading=heading.strip(),
                    text=body,
                )
            )
    return chunks


# --- embedding -------------------------------------------------------------

_genai_client = None


def _client():
    global _genai_client
    if _genai_client is None:
        from google import genai

        _genai_client = genai.Client(
            vertexai=config.USE_VERTEX,
            project=config.PROJECT_ID,
            location=config.LOCATION,
        )
    return _genai_client


def embed(text: str, *, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
    """Embed one passage. Caller is responsible for having redacted it."""
    from google.genai import types

    response = _client().models.embed_content(
        model=config.EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return list(response.embeddings[0].values)


# --- local keyword fallback ------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "is", "are", "was", "were",
    "be", "been", "to", "of", "in", "on", "at", "for", "with", "that", "this",
    "it", "as", "by", "from", "what", "which", "who", "how", "do", "does",
    "i", "you", "my", "me", "mean", "means", "should", "can", "about",
}


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def _keyword_score(query_tokens: List[str], chunk: Chunk) -> float:
    """Overlap score with the heading weighted up.

    Crude on purpose. Its job is to pick a plausible section out of ~13 when
    embeddings are unavailable, not to be a search engine.
    """
    if not query_tokens:
        return 0.0
    heading_tokens = set(_tokens(chunk.heading))
    body_tokens = _tokens(chunk.text)
    body_counts: dict[str, int] = {}
    for t in body_tokens:
        body_counts[t] = body_counts.get(t, 0) + 1

    score = 0.0
    for token in set(query_tokens):
        if token in heading_tokens:
            score += 3.0
        if token in body_counts:
            score += 1.0 + math.log1p(body_counts[token])
    return score


def _retrieve_local(query: str, k: int, chunks: List[Chunk]) -> List[Chunk]:
    query_tokens = _tokens(query)
    scored = [(_keyword_score(query_tokens, c), c) for c in chunks]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _s, c in scored[:k]]


# --- Firestore vector search ----------------------------------------------

def _retrieve_firestore(query: str, k: int, form_id: str) -> List[Chunk]:
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from google.cloud.firestore_v1.vector import Vector

    db = firestore.Client(project=config.PROJECT_ID)
    query_vector = Vector(embed(query, task_type="RETRIEVAL_QUERY"))
    results = (
        db.collection(config.FIRESTORE_COLLECTION)
        .where(filter=firestore.FieldFilter("form_id", "==", form_id))
        .find_nearest(
            vector_field="embedding",
            query_vector=query_vector,
            limit=k,
            distance_measure=DistanceMeasure.COSINE,
        )
        .get()
    )
    chunks = []
    for doc in results:
        data = doc.to_dict()
        chunks.append(
            Chunk(
                chunk_id=doc.id,
                form_id=data.get("form_id", form_id),
                heading=data.get("heading", ""),
                text=data.get("text", ""),
            )
        )
    return chunks


# --- public entry point ----------------------------------------------------

def retrieve(
    query: str,
    *,
    k: int = 3,
    form_id: str = config.DEMO_FORM_ID,
    chunks: Optional[List[Chunk]] = None,
) -> List[Chunk]:
    """Top-k guidance chunks for a question. Never raises: returns [] at worst.

    An empty list is a meaningful answer upstream — it makes the explainer
    say "I don't have guidance on that", which is the behaviour we want.
    """
    local_chunks = chunks if chunks is not None else load_corpus_chunks(form_id)

    if config.USE_STUB:
        return _retrieve_local(query, k, local_chunks)

    try:
        hits = _retrieve_firestore(query, k, form_id)
        if hits:
            return hits
        logger.warning("Firestore returned no chunks for %r; falling back to local", query)
    except Exception:
        logger.exception("Firestore retrieval failed; falling back to local corpus")

    return _retrieve_local(query, k, local_chunks)


def as_context_block(chunks: List[Chunk]) -> str:
    """Render retrieved chunks into the only text the explainer may speak from."""
    if not chunks:
        return "(no guidance retrieved)"
    return "\n\n".join(c.as_context() for c in chunks)
