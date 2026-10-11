"""The signpost is the only part of SnapKaki that touches the open web.

Two things are worth pinning: the domain guard, and the instruction that
keeps search locating rather than interpreting. Both are the difference
between "here is who is responsible" and "here is what your visa form
means, according to a content farm".
"""
import os

os.environ.setdefault("USE_STUB", "true")

import pytest

from app.agents.signpost import INSTRUCTION, Signpost, _looks_official


@pytest.mark.parametrize(
    "url",
    [
        "https://home-affairs.ec.europa.eu/policies/schengen-borders-and-visa_en",
        "https://www.gov.uk/standard-visitor",
        "https://www.ica.gov.sg/enter-depart/entry_requirements",
        "https://www.sem.admin.ch/sem/en/home.html",
        "https://www.udi.no/en/want-to-apply/visit-and-holiday/",
        "https://www.migrationsverket.se/en/",
    ],
)
def test_official_sources_pass(url):
    assert _looks_official(url), url


@pytest.mark.parametrize(
    "url",
    [
        "https://schengenvisainfo.com/requirements/",   # content farm
        "https://visa-agency.example.com/apply",        # commercial
        "https://udi.no.evil.example.com/",             # lookalike host
        "https://notudi.no/",                           # suffix without the dot
        "ftp://www.gov.uk/file",                        # not http(s)
        "not-a-url",
        "",
    ],
)
def test_everything_else_is_dropped(url):
    assert not _looks_official(url), url


def test_the_guard_fails_closed():
    """An unlisted but genuine authority is dropped rather than trusted.
    The user still gets the authority's name; they just get no link."""
    assert not _looks_official("https://immigration.govt.example/visa")


def test_instruction_forbids_explaining_the_form():
    """The whole safety argument for touching the web at all. If a tidy-up
    ever drops these lines, search quietly becomes an answering engine."""
    flat = " ".join(INSTRUCTION.split())
    assert "Do NOT explain any field" in flat
    assert "Do NOT summarise requirements" in flat
    assert "Only cite an OFFICIAL source" in flat
    assert "visa agency" in flat


def test_a_signpost_without_an_authority_is_not_useful():
    assert not Signpost().useful
    assert not Signpost(authority="Someone", confidence=0.2).useful
    assert Signpost(authority="Someone", confidence=0.9).useful


# --- read-aloud --------------------------------------------------------------

def test_hokkien_has_no_voice_and_we_do_not_fake_one():
    """Cloud TTS has no Hokkien voice. The nearest thing is a Mandarin
    reader on romanised Hokkien, which produces confident nonsense in a
    language the listener actually speaks. Silence is the honest answer."""
    from app import speech

    assert not speech.available_for("hokkien")
    assert speech.synthesise("Jit-e si sim-mih?", "hokkien") is None


def test_the_languages_we_claim_can_actually_be_spoken():
    from app import config, speech

    for code in ("en", "zh", "ms", "ta"):
        assert code in config.SUPPORTED_LANGUAGES
        assert speech.available_for(code), code


def test_speech_refuses_text_that_fails_the_pii_check(monkeypatch):
    """Audio is a second channel out of the system. The PII boundary covers
    every channel, not only the visible one."""
    from app import speech

    monkeypatch.setattr(
        speech, "assert_clean",
        lambda _t: (_ for _ in ()).throw(ValueError("pii")),
    )
    assert speech.synthesise("S1234567D", "en") is None


def test_empty_text_is_not_spoken():
    from app import speech

    assert speech.synthesise("", "en") is None
    assert speech.synthesise("   ", "en") is None
