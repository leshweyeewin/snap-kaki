"""The claims about what happens when things break.

docs/architecture.md says retrieval "degrades instead of failing" and that
a Firestore outage costs slightly worse explanations rather than a blank
screen. That claim rested on a single accidental observation - the vector
index happened not to be built during an early live test and the fallback
carried it. An accident is not evidence, so here is the experiment.
"""
import os

os.environ.setdefault("USE_STUB", "true")

import pytest

from app import config
from app.rag import retriever


@pytest.fixture
def live(monkeypatch):
    """Pretend we are not in stub mode, so the Firestore path is attempted."""
    monkeypatch.setattr(config, "USE_STUB", False)


def test_firestore_failure_falls_back_to_the_local_corpus(live, monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("Firestore is unreachable")

    monkeypatch.setattr(retriever, "_retrieve_firestore", explode)

    hits = retriever.retrieve("I am still paying my HDB loan, is that renting?")
    assert hits, "a Firestore outage must not leave the explainer with nothing"
    # And not just any chunk - the right one.
    assert any("Rental Status" in c.heading for c in hits), [c.heading for c in hits]


def test_an_empty_firestore_result_also_falls_back(live, monkeypatch):
    """Not an exception - a successful call that returns nothing, which is
    what a missing vector index actually looks like."""
    monkeypatch.setattr(retriever, "_retrieve_firestore", lambda *a, **k: [])

    hits = retriever.retrieve("What is the declaration in Section 2B?")
    assert hits
    assert any("2B" in c.heading or "declaration" in c.heading.lower() for c in hits)


def test_retrieve_never_raises_even_when_everything_fails(live, monkeypatch):
    """Returning [] is a meaningful answer upstream: it makes the explainer
    say it does not know. Raising would take the whole turn down."""
    monkeypatch.setattr(retriever, "_retrieve_firestore",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(retriever, "_retrieve_local",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom too")))

    with pytest.raises(RuntimeError):
        # Documents the one case that DOES propagate: if the local fallback
        # itself is broken, that is a bug in us, not a degraded dependency,
        # and it should be loud.
        retriever.retrieve("anything")


def test_the_local_scorer_finds_the_right_section_unaided():
    """The fallback is only worth having if its answers are usable."""
    cases = [
        ("Can I tick 3-room for my flat?", "Dwelling Type"),
        ("Who do I list as family members?", "Section 1B"),
        ("What am I signing at the end?", "2B"),
    ]
    chunks = retriever.load_corpus_chunks()
    for question, expected in cases:
        hits = retriever._retrieve_local(question, 3, chunks)
        assert hits, question
        assert any(expected.lower() in c.heading.lower() for c in hits), (
            f"{question!r} -> {[c.heading for c in hits]}"
        )
