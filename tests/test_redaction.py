"""Tests for the PII boundary.

These document what the patterns actually catch, including where they are
deliberately over-eager. Over-masking a field label costs us a slightly
vaguer explanation; under-masking sends someone's identification number to
a model. The trade is intentional.
"""
import pytest

from app.redaction import assert_clean, redact


def test_nric_is_masked():
    result = redact("My number is S1234567D thanks")
    assert "S1234567D" not in result.masked_text
    assert "[NRIC]" in result.masked_text
    assert result.found == {"NRIC": 1}
    assert result.has_pii


def test_lowercase_nric_is_masked():
    assert "[NRIC]" in redact("s1234567d").masked_text


def test_sg_mobile_is_masked():
    for raw in ["91234567", "8123 4567", "+65 9123 4567", "9123-4567"]:
        result = redact(f"call {raw}")
        assert "[PHONE]" in result.masked_text, raw


def test_email_is_masked():
    result = redact("write to ah.gong@example.com please")
    assert "[EMAIL]" in result.masked_text
    assert "ah.gong" not in result.masked_text


def test_postal_code_is_masked():
    assert "[POSTAL]" in redact("Singapore 310123").masked_text


def test_dob_is_masked():
    assert "[DOB]" in redact("born 3/4/1948").masked_text


def test_card_number_is_masked():
    result = redact("4111 1111 1111 1111")
    assert "4111" not in result.masked_text


def test_multiple_kinds_are_counted_separately():
    result = redact("S1234567D / 91234567 / a@b.co")
    assert set(result.found) == {"NRIC", "PHONE", "EMAIL"}


def test_clean_text_is_untouched():
    text = "What does Dwelling Type mean?"
    result = redact(text)
    assert result.masked_text == text
    assert not result.has_pii
    assert result.found == {}


def test_empty_and_none_are_safe():
    assert redact("").masked_text == ""
    assert redact(None).masked_text == ""
    assert not redact("").has_pii


def test_assert_clean_returns_masked_text():
    assert assert_clean("number S1234567D") == "number [NRIC]"


def test_assert_clean_passes_benign_text():
    text = "Circle one of Pink NRIC, Blue NRIC, Birth Certificate, FIN"
    # "NRIC" as a word is not an NRIC number, so this must survive intact -
    # the corpus and every CHAS field label depend on it.
    assert assert_clean(text) == text


def test_placeholders_survive_a_second_pass():
    """assert_clean re-scans its own output, so placeholders must not look
    like PII to the patterns that produced them."""
    once = assert_clean("S1234567D 91234567 a@b.co 310123 3/4/1948")
    assert assert_clean(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "Block 123 Toa Payoh",          # 3-digit block, not a postal code
        "3-room HDB",
        "Clause 11",
        "one letter, seven digits",
    ],
)
def test_form_vocabulary_is_not_over_masked(text):
    """Guards the corpus. If these started masking, every explanation about
    flat types or clause numbers would come out full of placeholders."""
    assert redact(text).masked_text == text
