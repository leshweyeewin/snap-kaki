"""Read the answer aloud.

The challenge names Elderlies under Information Accessibility, and until now
our answer to someone who struggles with a form was more text to read. For a
70-year-old with presbyopia squinting at a phone, that is not an answer. A
speaker button is the single most on-theme thing this product can do.

Two decisions worth stating.

**Hokkien gets no button.** Cloud Text-to-Speech has no Hokkien voice. The
nearest thing is a Mandarin voice reading romanised Hokkien, which would
produce confident nonsense in a language the listener actually speaks -
exactly the failure mode the rest of this codebase refuses. So the button is
hidden and the reason is given.

**The text is checked before it is spoken.** It is our own generated
explanation and should be clean already, but audio is a second channel out
of the system, and the PII boundary applies to every channel, not just the
visible one.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import config
from app.redaction import assert_clean

logger = logging.getLogger(__name__)

# Cloud TTS voices per app language. Chirp3-HD where it exists - these are
# read by people who find synthetic speech hard going, so the natural voice
# is worth the choice.
#
# hokkien is deliberately absent. See the module docstring.
VOICES = {
    "en": ("en-US", "en-US-Chirp3-HD-Achernar"),
    "zh": ("cmn-CN", "cmn-CN-Chirp3-HD-Achernar"),
    "ms": ("ms-MY", "ms-MY-Wavenet-A"),
    "ta": ("ta-IN", "ta-IN-Chirp3-HD-Achernar"),
}

# TTS bills per character and nothing we read aloud is long. A cap stops a
# runaway response turning into a runaway bill on a public endpoint.
MAX_CHARS = 1200

_client = None


def available_for(language: str) -> bool:
    return language in VOICES


def _get_client():
    global _client
    if _client is None:
        from google.cloud import texttospeech

        _client = texttospeech.TextToSpeechClient()
    return _client


def synthesise(text: str, language: str) -> Optional[bytes]:
    """MP3 bytes for `text`, or None if we cannot or should not speak it.

    Never raises: losing audio should cost the speaker button, not the turn.
    """
    if not text or not text.strip():
        return None
    if not available_for(language):
        return None

    try:
        clean = assert_clean(text)[:MAX_CHARS]
    except ValueError:
        logger.error("refusing to speak text that failed the PII check")
        return None

    if config.USE_STUB:
        return None

    try:
        from google.cloud import texttospeech

        language_code, voice_name = VOICES[language]
        response = _get_client().synthesize_speech(
            input=texttospeech.SynthesisInput(text=clean),
            voice=texttospeech.VoiceSelectionParams(
                language_code=language_code, name=voice_name
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                # Slightly under natural pace. The listener is being read
                # something consequential, often not in their first language.
                speaking_rate=0.92,
            ),
        )
        return response.audio_content
    except Exception:
        logger.exception("text-to-speech failed")
        return None
